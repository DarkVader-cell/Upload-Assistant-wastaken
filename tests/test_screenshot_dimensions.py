from src.takescreens import par_scaled_dimensions


def test_par_rounding_noise_keeps_stored_dimensions() -> None:
    assert par_scaled_dimensions(1920, 1080, 1.001, 1.0) is None
    assert par_scaled_dimensions(720, 576, 1.0, 1.004) is None


def test_par_meaningful_correction_emits_even_dimensions() -> None:
    assert par_scaled_dimensions(720, 576, 1.5, 1.0) == (1080, 576)
