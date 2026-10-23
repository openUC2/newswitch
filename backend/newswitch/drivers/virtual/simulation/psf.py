"""Little helper functions for PSF computation."""

from functools import cache

import numpy as np


@cache
def compute_psf(dz: float, a_dim: int, b_dim: int) -> np.ndarray:
    """Compute the point spread function for the given defocus."""
    try:
        import nipy as nip
        from nipy import para_abber

        IS_NIP = True
    except ImportError:
        IS_NIP = False

    dz = np.float32(dz)
    if IS_NIP:
        obj = nip.object_parameters()
        obj.type = obj.type_gaussian
        obj.a_dimension = a_dim
        obj.b_dimension = b_dim
        obj.gaussian_sigma = 1.0

        para_abber.aberration_types = [para_abber.aberration_zernikes.spheric]
        para_abber.aberration_strength = [np.float32(dz / 10.0)]
        psf = nip.psf(obj, para_abber)
        return psf.copy()
    else:
        return np.ones((a_dim, b_dim), dtype=np.float32)
