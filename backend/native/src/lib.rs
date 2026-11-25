//! newswitch's native writer: frames written straight from memory (a camera's ring slot, or any
//! array) as zarr v3 shards into an object store, S3 (mikro's datalayer, through the mesh's HTTP
//! proxy, with a prefix-scoped grant) or a local folder.
//!
//! An array is `(t, c, z, y, x)`. Each exposure fills one shard: `(1, colors, 1, H, W)`, the
//! colors of one plane, of inner chunks `(1, 1, 1, 256, 256)`. So a shard is complete once its
//! frame is written and is PUT once, whole: S3 has no partial writes, and nothing is buffered
//! across exposures. The format is zarr-python's default sharding: inner codecs `bytes` (little
//! endian) and `zstd` (level 0, no checksum), the index (`bytes`, `crc32c`) at the end; what
//! mikro's readers expect.
//!
//! `write` copies the frame once, from the address it is given into buffers of its own (splitting
//! interleaved colors into channels), and returns; encoding and the PUT run on worker threads,
//! and `write` waits while more than `max_in_flight_bytes` are not yet stored.
//!
//! An upload may be a pyramid (`add_level_s3`, `add_level_local`): each level is an array of its
//! own, the one before it halved in y and x (`max`, `mean` or `nearest` of each 2 x 2, as
//! `mikro.pyramid` builds them), made from the planes of each exposure as it is written and
//! stored beside it. Nothing is held between exposures; `t`, `c` and `z` keep their extent.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex, RwLock};

use bytes::Bytes;
use object_store::aws::{AmazonS3Builder, AwsCredential};
use object_store::local::LocalFileSystem;
use object_store::path::Path as StorePath;
use object_store::prefix::PrefixStore;
use object_store::{Certificate, ClientOptions, CredentialProvider, ObjectStore, PutPayload};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use tokio::runtime::Runtime;
use tokio::task::{JoinHandle, JoinSet};

/// The side of an inner chunk, in y and x.
const INNER: usize = 256;
/// What an empty index entry holds (zarr's "no chunk").
const MISSING: u64 = u64::MAX;

/// Credentials that can be replaced while the store is in use: a grant is refreshed before it
/// expires, and the writes in flight carry on with the new one.
#[derive(Debug)]
struct SwapCredentials {
    current: RwLock<Arc<AwsCredential>>,
}

#[async_trait::async_trait]
impl CredentialProvider for SwapCredentials {
    type Credential = AwsCredential;

    async fn get_credential(&self) -> object_store::Result<Arc<AwsCredential>> {
        Ok(self.current.read().expect("credentials lock").clone())
    }
}

fn credential(key: String, secret: String, token: Option<String>) -> Arc<AwsCredential> {
    Arc::new(AwsCredential { key_id: key, secret_key: secret, token })
}

/// How many bytes are written but not yet stored, and a signal when that falls.
struct InFlight {
    bytes: Mutex<u64>,
    freed: Condvar,
}

/// The array being written: its shape, sample size, and how a frame is laid out.
#[derive(Clone)]
struct Layout {
    shape: [u64; 5],
    colors: usize,
    height: usize,
    width: usize,
    sample: usize,
}

impl Layout {
    fn chunks_y(&self) -> usize {
        self.height.div_ceil(INNER)
    }

    fn chunks_x(&self) -> usize {
        self.width.div_ceil(INNER)
    }
}

/// The `zarr.json` of the array, as zarr-python 3 writes it for a sharded array.
fn array_metadata(layout: &Layout, dtype: &str, dims: &[String]) -> serde_json::Value {
    serde_json::json!({
        "zarr_format": 3,
        "node_type": "array",
        "shape": layout.shape,
        "data_type": dtype,
        "chunk_grid": {
            "name": "regular",
            // A shard's edge is a whole number of inner chunks: it reaches past the frame's
            // edge, where its chunks are padded with the fill value.
            "configuration": {"chunk_shape": [1, layout.colors, 1, layout.chunks_y() * INNER, layout.chunks_x() * INNER]},
        },
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
        "fill_value": 0,
        "codecs": [{
            "name": "sharding_indexed",
            "configuration": {
                "chunk_shape": [1, 1, 1, INNER, INNER],
                "codecs": [
                    {"name": "bytes", "configuration": {"endian": "little"}},
                    {"name": "zstd", "configuration": {"level": 0, "checksum": false}},
                ],
                "index_codecs": [
                    {"name": "bytes", "configuration": {"endian": "little"}},
                    {"name": "crc32c"},
                ],
                "index_location": "end",
            },
        }],
        "attributes": {},
        "dimension_names": dims,
        "storage_transformers": [],
    })
}

/// One shard: the inner chunks of each color plane, zstd-compressed, one after another, then
/// their index (offset and size of each, in C order over colors, chunk rows, chunk columns) and
/// that index's crc32c.
fn encode_shard(layout: &Layout, planes: &[Vec<u8>]) -> Result<Vec<u8>, String> {
    let (cy, cx, sample) = (layout.chunks_y(), layout.chunks_x(), layout.sample);
    let row_bytes = layout.width * sample;
    let mut data: Vec<u8> = Vec::new();
    let mut index: Vec<u8> = Vec::with_capacity(planes.len() * cy * cx * 16);
    let mut chunk = vec![0u8; INNER * INNER * sample];
    for plane in planes {
        for by in 0..cy {
            for bx in 0..cx {
                chunk.fill(0); // fill_value where the chunk runs past the frame
                let rows = INNER.min(layout.height - by * INNER);
                let cols = INNER.min(layout.width - bx * INNER) * sample;
                for r in 0..rows {
                    let from = (by * INNER + r) * row_bytes + bx * INNER * sample;
                    let to = r * INNER * sample;
                    chunk[to..to + cols].copy_from_slice(&plane[from..from + cols]);
                }
                let packed = zstd::bulk::compress(&chunk, 0).map_err(|e| format!("zstd: {e}"))?;
                index.extend_from_slice(&(data.len() as u64).to_le_bytes());
                index.extend_from_slice(&(packed.len() as u64).to_le_bytes());
                data.extend_from_slice(&packed);
            }
        }
    }
    let checksum = crc32c::crc32c(&index);
    data.extend_from_slice(&index);
    data.extend_from_slice(&checksum.to_le_bytes());
    let _ = MISSING; // every chunk of a shard is written: none is left out
    Ok(data)
}

/// Frames written as zarr v3 shards into an object store, as they come.
#[pyclass(module = "newswitch_native")]
struct ShardedUpload {
    runtime: Runtime,
    store: Arc<dyn ObjectStore>,
    credentials: Option<Arc<SwapCredentials>>,
    layout: Layout,
    max_in_flight: u64,
    in_flight: Arc<InFlight>,
    tasks: Mutex<Vec<JoinHandle<()>>>,
    errors: Arc<Mutex<Vec<String>>>,
    written: Arc<Mutex<u64>>,
    histograms: Arc<Mutex<Histograms>>,
}

/// How often each value occurs, by time point and channel, over every plane written there: one
/// count per possible value (256 for 8-bit samples, 65536 for 16-bit), so percentiles are exact.
type Histograms = BTreeMap<(u64, u64), Vec<u64>>;

/// Add the values of `plane` (samples of `sample` bytes, little endian) to `counts`.
fn count_into(counts: &mut [u64], plane: &[u8], sample: usize) {
    if sample == 1 {
        for &value in plane {
            counts[value as usize] += 1;
        }
    } else {
        for pair in plane.chunks_exact(2) {
            counts[u16::from_le_bytes([pair[0], pair[1]]) as usize] += 1;
        }
    }
}

fn runtime() -> PyResult<Runtime> {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .build()
        .map_err(|e| PyRuntimeError::new_err(format!("no runtime: {e}")))
}

fn layout_of(shape: Vec<u64>, dtype: &str, colors: u64) -> PyResult<Layout> {
    if shape.len() != 5 {
        return Err(PyValueError::new_err("an array is (t, c, z, y, x)"));
    }
    let sample = match dtype {
        "uint8" => 1,
        "uint16" => 2,
        other => return Err(PyValueError::new_err(format!("uint8 or uint16, not {other}"))),
    };
    if colors == 0 || shape[1] % colors != 0 {
        return Err(PyValueError::new_err(format!(
            "{} channels are no whole number of frames of {colors} colors",
            shape[1]
        )));
    }
    Ok(Layout {
        shape: [shape[0], shape[1], shape[2], shape[3], shape[4]],
        colors: colors as usize,
        height: shape[3] as usize,
        width: shape[4] as usize,
        sample,
    })
}

impl ShardedUpload {
    fn create(
        store: Arc<dyn ObjectStore>,
        credentials: Option<Arc<SwapCredentials>>,
        layout: Layout,
        dtype: &str,
        dims: Vec<String>,
        max_in_flight: u64,
    ) -> PyResult<Self> {
        if dims.len() != 5 {
            return Err(PyValueError::new_err("five dimension names: (t, c, z, y, x)"));
        }
        let runtime = runtime()?;
        let metadata = serde_json::to_vec_pretty(&array_metadata(&layout, dtype, &dims))
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        runtime
            .block_on(store.put(&StorePath::from("zarr.json"), PutPayload::from(metadata)))
            .map_err(|e| PyRuntimeError::new_err(format!("zarr.json not stored: {e}")))?;
        Ok(Self {
            runtime,
            store,
            credentials,
            layout,
            max_in_flight,
            in_flight: Arc::new(InFlight { bytes: Mutex::new(0), freed: Condvar::new() }),
            tasks: Mutex::new(Vec::new()),
            errors: Arc::new(Mutex::new(Vec::new())),
            written: Arc::new(Mutex::new(0)),
            histograms: Arc::new(Mutex::new(BTreeMap::new())),
        })
    }

    /// The frame at `address` split into one plane per color (the one copy): interleaved
    /// (height, width, colors), or `planar` (colors, height, width).
    fn planes(&self, address: usize, nbytes: usize, planar: bool) -> Vec<Vec<u8>> {
        let l = &self.layout;
        // SAFETY: the caller states `nbytes` readable bytes at `address`, laid out as it says,
        // in samples of `sample` bytes, and keeps them alive until `write` returns.
        let frame = unsafe { std::slice::from_raw_parts(address as *const u8, nbytes) };
        if l.colors == 1 || planar {
            return frame.chunks_exact(nbytes / l.colors).map(<[u8]>::to_vec).collect();
        }
        // One strided pass per color, each color on a thread of its own: plain loops the
        // compiler vectorizes (a sub-slice copy per sample does not, and is ten times slower).
        let pixels = l.height * l.width;
        let (colors, sample) = (l.colors, l.sample);
        let planes: Vec<Vec<u8>> = std::thread::scope(|scope| {
            let workers: Vec<_> = (0..colors)
                .map(|k| {
                    scope.spawn(move || {
                        let mut plane = Vec::with_capacity(pixels * sample);
                        if sample == 1 {
                            plane.extend(frame[k..].iter().step_by(colors));
                        } else {
                            for i in 0..pixels {
                                let at = (i * colors + k) * 2;
                                plane.push(frame[at]);
                                plane.push(frame[at + 1]);
                            }
                        }
                        plane
                    })
                })
                .collect();
            workers.into_iter().map(|w| w.join().expect("plane thread")).collect()
        });
        planes
    }
}

#[pymethods]
impl ShardedUpload {
    /// An array under `prefix` in `bucket` of an S3 `endpoint`, through `proxy` if given, with
    /// temporary credentials (a grant's), trusting `certificates` (PEM) besides the system's.
    #[staticmethod]
    #[pyo3(signature = (endpoint, bucket, prefix, access_key, secret_key, session_token, shape, dtype, dims, colors, proxy=None, certificates=Vec::new(), max_in_flight_bytes=256 * 1024 * 1024))]
    #[allow(clippy::too_many_arguments)]
    fn s3(
        endpoint: String,
        bucket: String,
        prefix: String,
        access_key: String,
        secret_key: String,
        session_token: Option<String>,
        shape: Vec<u64>,
        dtype: &str,
        dims: Vec<String>,
        colors: u64,
        proxy: Option<String>,
        certificates: Vec<String>,
        max_in_flight_bytes: u64,
    ) -> PyResult<Self> {
        let layout = layout_of(shape, dtype, colors)?;
        let credentials = Arc::new(SwapCredentials {
            current: RwLock::new(credential(access_key, secret_key, session_token)),
        });
        let mut options = ClientOptions::new().with_allow_http(endpoint.starts_with("http://"));
        if let Some(proxy) = proxy {
            options = options.with_proxy_url(proxy);
        }
        for pem in &certificates {
            let certificate = Certificate::from_pem(pem.as_bytes())
                .map_err(|e| PyValueError::new_err(format!("certificate: {e}")))?;
            options = options.with_root_certificate(certificate);
        }
        let s3 = AmazonS3Builder::new()
            .with_endpoint(endpoint)
            .with_bucket_name(bucket)
            .with_region("us-east-1")
            .with_virtual_hosted_style_request(false)
            .with_credentials(credentials.clone())
            .with_client_options(options)
            .build()
            .map_err(|e| PyValueError::new_err(format!("S3 store: {e}")))?;
        let store: Arc<dyn ObjectStore> = Arc::new(PrefixStore::new(s3, prefix.as_str()));
        Self::create(store, Some(credentials), layout, dtype, dims, max_in_flight_bytes)
    }

    /// An array in the folder `root` (made if missing): for tests, and runs without S3.
    #[staticmethod]
    #[pyo3(signature = (root, shape, dtype, dims, colors, max_in_flight_bytes=256 * 1024 * 1024))]
    fn local(
        root: &str,
        shape: Vec<u64>,
        dtype: &str,
        dims: Vec<String>,
        colors: u64,
        max_in_flight_bytes: u64,
    ) -> PyResult<Self> {
        std::fs::create_dir_all(root).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let local = LocalFileSystem::new_with_prefix(root)
            .map_err(|e| PyValueError::new_err(format!("folder: {e}")))?;
        let layout = layout_of(shape, dtype, colors)?;
        Self::create(Arc::new(local), None, layout, dtype, dims, max_in_flight_bytes)
    }

    /// Write the frame of `nbytes` at `address` as time `t`, channels `c0 .. c0 + colors`,
    /// plane `z`: (height, width, colors) samples, interleaved, or (colors, height, width) when
    /// `planar`. Returns once it is copied (the memory at `address` may then be reused); it is
    /// stored in the background.
    #[pyo3(signature = (t, c0, z, address, nbytes, height, width, channels, bytes_per_sample, planar=false))]
    #[allow(clippy::too_many_arguments)]
    fn write(
        &self,
        py: Python<'_>,
        t: u64,
        c0: u64,
        z: u64,
        address: usize,
        nbytes: usize,
        height: usize,
        width: usize,
        channels: usize,
        bytes_per_sample: usize,
        planar: bool,
    ) -> PyResult<()> {
        let l = self.layout.clone();
        if height != l.height || width != l.width || channels != l.colors || bytes_per_sample != l.sample {
            return Err(PyValueError::new_err(format!(
                "a frame of {height} x {width} x {channels} of {bytes_per_sample} bytes, not the array's \
                 {} x {} x {} of {}",
                l.height, l.width, l.colors, l.sample
            )));
        }
        if nbytes != height * width * channels * bytes_per_sample {
            return Err(PyValueError::new_err(format!("{nbytes} bytes are no such frame")));
        }
        if t >= l.shape[0] || z >= l.shape[2] || c0 % l.colors as u64 != 0 || c0 >= l.shape[1] {
            return Err(PyValueError::new_err(format!("no place t={t}, c={c0}, z={z} in {:?}", l.shape)));
        }
        if address == 0 {
            return Err(PyValueError::new_err("no frame at address 0"));
        }
        py.allow_threads(|| {
            // Wait while too much is unstored (a lone frame is always let through).
            let need = nbytes as u64;
            let mut pending = self.in_flight.bytes.lock().expect("in-flight lock");
            while *pending > 0 && *pending + need > self.max_in_flight {
                pending = self.in_flight.freed.wait(pending).expect("in-flight lock");
            }
            *pending += need;
            drop(pending);

            let planes = self.planes(address, nbytes, planar);
            let key = StorePath::from(format!("c/{t}/{}/{z}/0/0", c0 / l.colors as u64));
            let (store, in_flight, errors, written, histograms) = (
                self.store.clone(),
                self.in_flight.clone(),
                self.errors.clone(),
                self.written.clone(),
                self.histograms.clone(),
            );
            let task = self.runtime.spawn(async move {
                let layout = l.clone();
                let stored = async {
                    let shard = tokio::task::spawn_blocking(move || {
                        // Counted here, beside the encoding: off the caller's thread.
                        let values = 1usize << (8 * layout.sample);
                        let counted: Vec<Vec<u64>> = planes
                            .iter()
                            .map(|plane| {
                                let mut counts = vec![0u64; values];
                                count_into(&mut counts, plane, layout.sample);
                                counts
                            })
                            .collect();
                        {
                            let mut all = histograms.lock().expect("histograms lock");
                            for (k, counts) in counted.into_iter().enumerate() {
                                let entry = all
                                    .entry((t, c0 + k as u64))
                                    .or_insert_with(|| vec![0u64; values]);
                                for (sum, n) in entry.iter_mut().zip(counts) {
                                    *sum += n;
                                }
                            }
                        }
                        encode_shard(&layout, &planes)
                    })
                    .await
                    .map_err(|e| e.to_string())??;
                    let size = shard.len() as u64;
                    store
                        .put(&key, PutPayload::from(Bytes::from(shard)))
                        .await
                        .map_err(|e| format!("{key}: {e}"))?;
                    Ok::<u64, String>(size)
                }
                .await;
                match stored {
                    Ok(size) => *written.lock().expect("written lock") += size,
                    Err(e) => errors.lock().expect("errors lock").push(e),
                }
                let mut pending = in_flight.bytes.lock().expect("in-flight lock");
                *pending -= need;
                in_flight.freed.notify_all();
            });
            self.tasks.lock().expect("tasks lock").push(task);
        });
        Ok(())
    }

    /// Replace the credentials (a refreshed grant's): what is still to be stored uses them.
    #[pyo3(signature = (access_key, secret_key, session_token=None))]
    fn set_credentials(&self, access_key: String, secret_key: String, session_token: Option<String>) -> PyResult<()> {
        let Some(credentials) = &self.credentials else {
            return Err(PyValueError::new_err("a local array has no credentials"));
        };
        *credentials.current.write().expect("credentials lock") = credential(access_key, secret_key, session_token);
        Ok(())
    }

    /// How often each value occurs in what was stored so far, by time point and channel (over
    /// every plane): ``[(t, c, counts)]``, ``counts`` little-endian u64, one per possible value.
    /// Complete once `finish` returned.
    fn histograms<'py>(&self, py: Python<'py>) -> Vec<(u64, u64, Bound<'py, pyo3::types::PyBytes>)> {
        let all = self.histograms.lock().expect("histograms lock");
        all.iter()
            .map(|(&(t, c), counts)| {
                let bytes: Vec<u8> = counts.iter().flat_map(|n| n.to_le_bytes()).collect();
                (t, c, pyo3::types::PyBytes::new(py, &bytes))
            })
            .collect()
    }

    /// How many bytes are written but not yet stored.
    #[getter]
    fn pending_bytes(&self) -> u64 {
        *self.in_flight.bytes.lock().expect("in-flight lock")
    }

    /// Wait until every frame written is stored; the bytes stored (shards, without zarr.json).
    ///
    /// Raises:
    ///     RuntimeError: A shard could not be stored (each is named).
    fn finish(&self, py: Python<'_>) -> PyResult<u64> {
        let tasks: Vec<JoinHandle<()>> = std::mem::take(&mut *self.tasks.lock().expect("tasks lock"));
        py.allow_threads(|| {
            self.runtime.block_on(async {
                for task in tasks {
                    let _ = task.await;
                }
            })
        });
        let errors = self.errors.lock().expect("errors lock");
        if !errors.is_empty() {
            return Err(PyRuntimeError::new_err(format!("not stored: {}", errors.join("; "))));
        }
        Ok(*self.written.lock().expect("written lock"))
    }
}

#[pymodule]
fn newswitch_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<ShardedUpload>()?;
    Ok(())
}
