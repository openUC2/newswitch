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
//! and `write` waits while more than its budget allows are not yet stored: its own
//! (`max_in_flight_bytes`), or an `InFlightBudget` it shares with other uploads, so that every
//! record streamed at once is bounded together.
//!
//! An upload may be a pyramid (`add_level_s3`, `add_level_local`): each level is an array of its
//! own, the one before it halved in y and x (`max`, `mean` or `nearest` of each 2 x 2, as
//! `mikro.pyramid` builds them), made from the planes of each exposure as it is written and
//! stored beside it. Nothing is held between exposures; `t`, `c` and `z` keep their extent.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
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

/// How many bytes are written but not yet stored, how many may be, and a signal when that falls.
struct InFlight {
    bytes: Mutex<u64>,
    freed: Condvar,
    limit: AtomicU64,
}

impl InFlight {
    fn new(limit: u64) -> Arc<Self> {
        Arc::new(Self { bytes: Mutex::new(0), freed: Condvar::new(), limit: AtomicU64::new(limit) })
    }
}

/// How much may be written and not yet stored, over every upload given it: what each `write`
/// waits for beyond it (a lone frame is always let through).
#[pyclass(module = "newswitch_native")]
struct InFlightBudget {
    inner: Arc<InFlight>,
}

#[pymethods]
impl InFlightBudget {
    #[new]
    fn new(limit_bytes: u64) -> Self {
        Self { inner: InFlight::new(limit_bytes) }
    }

    /// How many bytes may be unstored at once.
    #[getter]
    fn limit(&self) -> u64 {
        self.inner.limit.load(Ordering::SeqCst)
    }

    /// Change it: writes waiting are let through if it grew.
    #[setter]
    fn set_limit(&self, limit_bytes: u64) {
        self.inner.limit.store(limit_bytes, Ordering::SeqCst);
        self.inner.freed.notify_all();
    }

    /// How many bytes are written but not yet stored, by every upload given it.
    #[getter]
    fn pending_bytes(&self) -> u64 {
        *self.inner.bytes.lock().expect("in-flight lock")
    }
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

/// How a pyramid level is made of the one before it, from each 2 x 2 of its samples: as
/// `mikro.pyramid` makes it, so a level written here is the one mikro's own builder would make.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Reduction {
    /// The largest: thin bright structures stay visible. An odd edge's last row or column is
    /// left out.
    Max,
    /// The mean, rounded down (numpy's mean, cast back). An odd edge's last row or column is
    /// left out.
    Mean,
    /// The first of each pair: a stride, which keeps an odd edge's last sample.
    Nearest,
}

fn reduction_of(name: &str) -> PyResult<Reduction> {
    match name {
        "max" => Ok(Reduction::Max),
        "mean" => Ok(Reduction::Mean),
        "nearest" => Ok(Reduction::Nearest),
        other => Err(PyValueError::new_err(format!("max, mean or nearest, not {other}"))),
    }
}

impl Layout {
    /// The layout of the level below this one: y and x halved, as `reduction` trims them.
    fn halved(&self, reduction: Reduction) -> Layout {
        let half = |n: usize| if reduction == Reduction::Nearest { n.div_ceil(2) } else { n / 2 };
        let (height, width) = (half(self.height), half(self.width));
        Layout {
            shape: [self.shape[0], self.shape[1], self.shape[2], height as u64, width as u64],
            height,
            width,
            ..self.clone()
        }
    }

    /// The bytes of one exposure at this level: every color's plane.
    fn frame_bytes(&self) -> u64 {
        (self.height * self.width * self.colors * self.sample) as u64
    }
}

/// A sample as stored: little endian, of one or two bytes.
trait Sample: Copy + Ord {
    const SIZE: usize;
    fn read(bytes: &[u8]) -> Self;
    fn push(self, out: &mut Vec<u8>);
    fn mean(a: Self, b: Self, c: Self, d: Self) -> Self;
}

impl Sample for u8 {
    const SIZE: usize = 1;
    fn read(bytes: &[u8]) -> Self {
        bytes[0]
    }
    fn push(self, out: &mut Vec<u8>) {
        out.push(self);
    }
    fn mean(a: Self, b: Self, c: Self, d: Self) -> Self {
        ((a as u32 + b as u32 + c as u32 + d as u32) / 4) as u8
    }
}

impl Sample for u16 {
    const SIZE: usize = 2;
    fn read(bytes: &[u8]) -> Self {
        u16::from_le_bytes([bytes[0], bytes[1]])
    }
    fn push(self, out: &mut Vec<u8>) {
        out.extend_from_slice(&self.to_le_bytes());
    }
    fn mean(a: Self, b: Self, c: Self, d: Self) -> Self {
        ((a as u32 + b as u32 + c as u32 + d as u32) / 4) as u16
    }
}

/// One color's `plane` of `from`, halved into `to` by `reduction`.
fn halve(plane: &[u8], from: &Layout, to: &Layout, reduction: Reduction) -> Vec<u8> {
    match from.sample {
        1 => halve_as::<u8>(plane, from.width, to, reduction),
        _ => halve_as::<u16>(plane, from.width, to, reduction),
    }
}

fn halve_as<T: Sample>(plane: &[u8], from_width: usize, to: &Layout, reduction: Reduction) -> Vec<u8> {
    let row = from_width * T::SIZE;
    let at = |line: &[u8], x: usize| T::read(&line[x * T::SIZE..]);
    let mut out = Vec::with_capacity(to.height * to.width * T::SIZE);
    for y in 0..to.height {
        let upper = &plane[2 * y * row..];
        if reduction == Reduction::Nearest {
            for x in 0..to.width {
                at(upper, 2 * x).push(&mut out);
            }
            continue;
        }
        let lower = &plane[(2 * y + 1) * row..];
        for x in 0..to.width {
            let (a, b, c, d) = (at(upper, 2 * x), at(upper, 2 * x + 1), at(lower, 2 * x), at(lower, 2 * x + 1));
            let value = match reduction {
                Reduction::Max => a.max(b).max(c.max(d)),
                _ => T::mean(a, b, c, d),
            };
            value.push(&mut out);
        }
    }
    out
}

/// One array of the upload: level 0, the frames as they are, or a level of its pyramid.
struct Level {
    store: Arc<dyn ObjectStore>,
    credentials: Option<Arc<SwapCredentials>>,
    layout: Layout,
}

/// Where an upload's S3 arrays are: what each level's store is built with, beside its grant.
#[derive(Clone)]
struct S3Origin {
    endpoint: String,
    proxy: Option<String>,
    certificates: Vec<String>,
}

/// The array under `prefix` in `bucket` of `origin`, with `credentials`.
fn s3_store(
    origin: &S3Origin,
    bucket: String,
    prefix: &str,
    credentials: Arc<SwapCredentials>,
) -> PyResult<Arc<dyn ObjectStore>> {
    let mut options = ClientOptions::new().with_allow_http(origin.endpoint.starts_with("http://"));
    if let Some(proxy) = &origin.proxy {
        options = options.with_proxy_url(proxy);
    }
    for pem in &origin.certificates {
        let certificate = Certificate::from_pem(pem.as_bytes())
            .map_err(|e| PyValueError::new_err(format!("certificate: {e}")))?;
        options = options.with_root_certificate(certificate);
    }
    let s3 = AmazonS3Builder::new()
        .with_endpoint(origin.endpoint.clone())
        .with_bucket_name(bucket)
        .with_region("us-east-1")
        .with_virtual_hosted_style_request(false)
        .with_credentials(credentials)
        .with_client_options(options)
        .build()
        .map_err(|e| PyValueError::new_err(format!("S3 store: {e}")))?;
    Ok(Arc::new(PrefixStore::new(s3, prefix)))
}

/// The folder `root` (made if missing) as a store.
fn local_store(root: &str) -> PyResult<Arc<dyn ObjectStore>> {
    std::fs::create_dir_all(root).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let local = LocalFileSystem::new_with_prefix(root)
        .map_err(|e| PyValueError::new_err(format!("folder: {e}")))?;
    Ok(Arc::new(local))
}

/// Frames written as zarr v3 shards into an object store, as they come; and, if it has levels,
/// each halved into every level of its pyramid.
#[pyclass(module = "newswitch_native")]
struct ShardedUpload {
    runtime: Runtime,
    /// Level 0 first, then each coarser one.
    levels: RwLock<Vec<Arc<Level>>>,
    s3: Option<S3Origin>,
    dtype: String,
    dims: Vec<String>,
    reduction: Reduction,
    /// Whether a frame was written: levels are added before.
    started: AtomicBool,
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

/// The budget an upload waits on: the one it is given, shared, or one of its own.
fn in_flight_of(budget: Option<PyRef<'_, InFlightBudget>>, max_in_flight_bytes: u64) -> Arc<InFlight> {
    match budget {
        Some(budget) => budget.inner.clone(),
        None => InFlight::new(max_in_flight_bytes),
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
    #[allow(clippy::too_many_arguments)]
    fn create(
        store: Arc<dyn ObjectStore>,
        credentials: Option<Arc<SwapCredentials>>,
        s3: Option<S3Origin>,
        layout: Layout,
        dtype: &str,
        dims: Vec<String>,
        reduction: &str,
        in_flight: Arc<InFlight>,
    ) -> PyResult<Self> {
        if dims.len() != 5 {
            return Err(PyValueError::new_err("five dimension names: (t, c, z, y, x)"));
        }
        let reduction = reduction_of(reduction)?;
        let runtime = runtime()?;
        let upload = Self {
            runtime,
            levels: RwLock::new(Vec::new()),
            s3,
            dtype: dtype.to_string(),
            dims,
            reduction,
            started: AtomicBool::new(false),
            in_flight,
            tasks: Mutex::new(Vec::new()),
            errors: Arc::new(Mutex::new(Vec::new())),
            written: Arc::new(Mutex::new(0)),
            histograms: Arc::new(Mutex::new(BTreeMap::new())),
        };
        upload.begin(Level { store, credentials, layout })?;
        Ok(upload)
    }

    /// Store `level`'s `zarr.json` and add it, the next coarser one.
    fn begin(&self, level: Level) -> PyResult<()> {
        let metadata = serde_json::to_vec_pretty(&array_metadata(&level.layout, &self.dtype, &self.dims))
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        self.runtime
            .block_on(level.store.put(&StorePath::from("zarr.json"), PutPayload::from(metadata)))
            .map_err(|e| PyRuntimeError::new_err(format!("zarr.json not stored: {e}")))?;
        self.levels.write().expect("levels lock").push(Arc::new(level));
        Ok(())
    }

    /// The layout of the level that would come next, once checked that one can.
    fn next_layout(&self) -> PyResult<Layout> {
        if self.started.load(Ordering::SeqCst) {
            return Err(PyValueError::new_err("a level is added before the first frame is written"));
        }
        let levels = self.levels.read().expect("levels lock");
        let last = &levels.last().expect("level 0").layout;
        if last.height < 2 || last.width < 2 {
            return Err(PyValueError::new_err(format!(
                "a level of {} x {} is not halved again",
                last.height, last.width
            )));
        }
        Ok(last.halved(self.reduction))
    }

    /// The frame at `address` split into one plane per color (the one copy): interleaved
    /// (height, width, colors), or `planar` (colors, height, width).
    fn planes(&self, l: &Layout, address: usize, nbytes: usize, planar: bool) -> Vec<Vec<u8>> {
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
    /// Its pyramid's levels, if any are added, are made by `reduction` (max, mean or nearest).
    #[staticmethod]
    #[pyo3(signature = (endpoint, bucket, prefix, access_key, secret_key, session_token, shape, dtype, dims, colors, proxy=None, certificates=Vec::new(), max_in_flight_bytes=256 * 1024 * 1024, reduction="max", budget=None))]
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
        reduction: &str,
        budget: Option<PyRef<'_, InFlightBudget>>,
    ) -> PyResult<Self> {
        let layout = layout_of(shape, dtype, colors)?;
        let credentials = Arc::new(SwapCredentials {
            current: RwLock::new(credential(access_key, secret_key, session_token)),
        });
        let origin = S3Origin { endpoint, proxy, certificates };
        let store = s3_store(&origin, bucket, &prefix, credentials.clone())?;
        let in_flight = in_flight_of(budget, max_in_flight_bytes);
        Self::create(store, Some(credentials), Some(origin), layout, dtype, dims, reduction, in_flight)
    }

    /// An array in the folder `root` (made if missing): for tests, and runs without S3.
    #[staticmethod]
    #[pyo3(signature = (root, shape, dtype, dims, colors, max_in_flight_bytes=256 * 1024 * 1024, reduction="max", budget=None))]
    #[allow(clippy::too_many_arguments)]
    fn local(
        root: &str,
        shape: Vec<u64>,
        dtype: &str,
        dims: Vec<String>,
        colors: u64,
        max_in_flight_bytes: u64,
        reduction: &str,
        budget: Option<PyRef<'_, InFlightBudget>>,
    ) -> PyResult<Self> {
        let store = local_store(root)?;
        let layout = layout_of(shape, dtype, colors)?;
        let in_flight = in_flight_of(budget, max_in_flight_bytes);
        Self::create(store, None, None, layout, dtype, dims, reduction, in_flight)
    }

    /// Add the next level of the pyramid, under `prefix` in `bucket` of this upload's endpoint
    /// (a grant of its own): the last level halved in y and x. Its shape.
    ///
    /// Raises:
    ///     ValueError: A frame was written already, the last level is too small to halve, or
    ///         this upload is not into S3.
    #[pyo3(signature = (bucket, prefix, access_key, secret_key, session_token=None))]
    fn add_level_s3(
        &self,
        bucket: String,
        prefix: String,
        access_key: String,
        secret_key: String,
        session_token: Option<String>,
    ) -> PyResult<Vec<u64>> {
        let Some(origin) = &self.s3 else {
            return Err(PyValueError::new_err("a local array's levels are local (add_level_local)"));
        };
        let layout = self.next_layout()?;
        let credentials = Arc::new(SwapCredentials {
            current: RwLock::new(credential(access_key, secret_key, session_token)),
        });
        let store = s3_store(origin, bucket, &prefix, credentials.clone())?;
        let shape = layout.shape.to_vec();
        self.begin(Level { store, credentials: Some(credentials), layout })?;
        Ok(shape)
    }

    /// Add the next level of the pyramid in the folder `root` (made if missing): the last level
    /// halved in y and x. Its shape.
    ///
    /// Raises:
    ///     ValueError: A frame was written already, or the last level is too small to halve.
    fn add_level_local(&self, root: &str) -> PyResult<Vec<u64>> {
        let layout = self.next_layout()?;
        let store = local_store(root)?;
        let shape = layout.shape.to_vec();
        self.begin(Level { store, credentials: None, layout })?;
        Ok(shape)
    }

    /// How many arrays are written: level 0 and the pyramid's.
    #[getter]
    fn levels(&self) -> usize {
        self.levels.read().expect("levels lock").len()
    }

    /// Write the frame of `nbytes` at `address` as time `t`, channels `c0 .. c0 + colors`,
    /// plane `z`: (height, width, colors) samples, interleaved, or (colors, height, width) when
    /// `planar`. Returns once it is copied (the memory at `address` may then be reused); it is
    /// stored in the background, and halved into every level.
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
        self.started.store(true, Ordering::SeqCst);
        let levels: Vec<Arc<Level>> = self.levels.read().expect("levels lock").clone();
        let l = levels[0].layout.clone();
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
        let reduction = self.reduction;
        py.allow_threads(|| {
            // Wait while too much is unstored (a lone frame is always let through): the frame
            // at every level, as each is held until stored.
            let need: u64 = levels.iter().map(|level| level.layout.frame_bytes()).sum();
            let mut pending = self.in_flight.bytes.lock().expect("in-flight lock");
            while *pending > 0 && *pending + need > self.in_flight.limit.load(Ordering::SeqCst) {
                pending = self.in_flight.freed.wait(pending).expect("in-flight lock");
            }
            *pending += need;
            drop(pending);

            let planes = self.planes(&l, address, nbytes, planar);
            let key = StorePath::from(format!("c/{t}/{}/{z}/0/0", c0 / l.colors as u64));
            let (in_flight, errors, written, histograms) = (
                self.in_flight.clone(),
                self.errors.clone(),
                self.written.clone(),
                self.histograms.clone(),
            );
            let task = self.runtime.spawn(async move {
                let stored = async {
                    let shards = tokio::task::spawn_blocking(move || {
                        let layout = &levels[0].layout;
                        // Counted here, beside the encoding: off the caller's thread; of level 0.
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
                        // Each level of the one before: one shard each, the planes then dropped.
                        let mut shards = Vec::with_capacity(levels.len());
                        let mut planes = planes;
                        for (k, level) in levels.iter().enumerate() {
                            if k > 0 {
                                let from = &levels[k - 1].layout;
                                planes = planes
                                    .iter()
                                    .map(|plane| halve(plane, from, &level.layout, reduction))
                                    .collect();
                            }
                            shards.push((k, level.clone(), encode_shard(&level.layout, &planes)?));
                        }
                        Ok::<_, String>(shards)
                    })
                    .await
                    .map_err(|e| e.to_string())??;
                    let mut puts = JoinSet::new();
                    for (k, level, shard) in shards {
                        let key = key.clone();
                        puts.spawn(async move {
                            let size = shard.len() as u64;
                            level
                                .store
                                .put(&key, PutPayload::from(Bytes::from(shard)))
                                .await
                                .map_err(|e| format!("level {k} {key}: {e}"))?;
                            Ok::<u64, String>(size)
                        });
                    }
                    let (mut size, mut failed) = (0u64, Vec::new());
                    while let Some(put) = puts.join_next().await {
                        match put {
                            Ok(Ok(n)) => size += n,
                            Ok(Err(e)) => failed.push(e),
                            Err(e) => failed.push(e.to_string()),
                        }
                    }
                    if failed.is_empty() {
                        Ok(size)
                    } else {
                        Err(failed.join("; "))
                    }
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

    /// Replace the credentials of `level` (a refreshed grant's): what is still to be stored
    /// there uses them.
    #[pyo3(signature = (access_key, secret_key, session_token=None, level=0))]
    fn set_credentials(
        &self,
        access_key: String,
        secret_key: String,
        session_token: Option<String>,
        level: usize,
    ) -> PyResult<()> {
        let levels = self.levels.read().expect("levels lock");
        let Some(found) = levels.get(level) else {
            return Err(PyValueError::new_err(format!("no level {level} of {}", levels.len())));
        };
        let Some(credentials) = &found.credentials else {
            return Err(PyValueError::new_err("a local array has no credentials"));
        };
        *credentials.current.write().expect("credentials lock") = credential(access_key, secret_key, session_token);
        Ok(())
    }

    /// How often each value occurs in what was stored so far, by time point and channel (over
    /// every plane, of level 0): ``[(t, c, counts)]``, ``counts`` little-endian u64, one per
    /// possible value. Complete once `finish` returned.
    fn histograms<'py>(&self, py: Python<'py>) -> Vec<(u64, u64, Bound<'py, pyo3::types::PyBytes>)> {
        let all = self.histograms.lock().expect("histograms lock");
        all.iter()
            .map(|(&(t, c), counts)| {
                let bytes: Vec<u8> = counts.iter().flat_map(|n| n.to_le_bytes()).collect();
                (t, c, pyo3::types::PyBytes::new(py, &bytes))
            })
            .collect()
    }

    /// How many bytes are written but not yet stored (at every level; by every upload sharing
    /// its budget).
    #[getter]
    fn pending_bytes(&self) -> u64 {
        *self.in_flight.bytes.lock().expect("in-flight lock")
    }

    /// Wait until every frame written is stored; the bytes stored (shards of every level,
    /// without zarr.json).
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
    module.add_class::<InFlightBudget>()?;
    Ok(())
}
