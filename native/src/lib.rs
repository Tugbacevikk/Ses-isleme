use pyo3::prelude::*;

/// 1. High-Performance Rust Linear Resampling to 16,000 Hz
/// Ses dalgasını hedef 16kHz örnekleme hızına Rust ile yüksek hızda dönüştürür.
#[pyfunction]
fn resample_pcm_16k(data: Vec<f32>, original_sr: usize) -> PyResult<Vec<f32>> {
    if original_sr == 16000 || data.is_empty() {
        return Ok(data);
    }

    let target_sr = 16000;
    let ratio = original_sr as f64 / target_sr as f64;
    let new_len = (data.len() as f64 / ratio) as usize;
    let mut resampled = Vec::with_capacity(new_len);

    for i in 0..new_len {
        let orig_pos = i as f64 * ratio;
        let index = orig_pos as usize;
        let frac = orig_pos - index as f64;

        if index + 1 < data.len() {
            let val = data[index] as f64 * (1.0 - frac) + data[index + 1] as f64 * frac;
            resampled.push(val as f32);
        } else if index < data.len() {
            resampled.push(data[index]);
        }
    }

    Ok(resampled)
}

/// 2. Rust Zero-Latency Voice Activity Detection (VAD) Frame Energy Calculation
/// Ses karesinin RMS (Root Mean Square) enerjisini hesaplayıp konuşma/sessizlik kararı verir.
#[pyfunction]
fn calculate_signal_energy_vad(data: Vec<f32>, frame_size: usize, threshold: f32) -> PyResult<Vec<bool>> {
    if data.is_empty() || frame_size == 0 {
        return Ok(Vec::new());
    }

    let num_frames = data.len() / frame_size;
    let mut vad_flags = Vec::with_capacity(num_frames);

    for i in 0..num_frames {
        let start = i * frame_size;
        let end = start + frame_size;
        let frame = &data[start..end];

        let sum_sq: f64 = frame.iter().map(|&x| (x as f64) * (x as f64)).sum();
        let rms = (sum_sq / frame_size as f64).sqrt() as f32;

        vad_flags.push(rms >= threshold);
    }

    Ok(vad_flags)
}

/// 3. Ultra-Fast Cosine Similarity Calculation for Speaker Embeddings
/// İki konuşmacı vektörü arasındaki kosinüs benzerliğini hesaplar (Konuşmacı Eşleme).
#[pyfunction]
fn compute_cosine_similarity(vec_a: Vec<f32>, vec_b: Vec<f32>) -> PyResult<f32> {
    if vec_a.len() != vec_b.len() || vec_a.is_empty() {
        return Ok(0.0);
    }

    let mut dot_product: f64 = 0.0;
    let mut norm_a: f64 = 0.0;
    let mut norm_b: f64 = 0.0;

    for i in 0..vec_a.len() {
        let a = vec_a[i] as f64;
        let b = vec_b[i] as f64;

        dot_product += a * b;
        norm_a += a * a;
        norm_b += b * b;
    }

    if norm_a == 0.0 || norm_b == 0.0 {
        return Ok(0.0);
    }

    let similarity = dot_product / (norm_a.sqrt() * norm_b.sqrt());
    Ok(similarity as f32)
}

/// PyO3 C-ABI Python Modül Bağlayıcısı
#[pymodule]
fn native_audio_dsp(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(resample_pcm_16k, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_signal_energy_vad, m)?)?;
    m.add_function(wrap_pyfunction!(compute_cosine_similarity, m)?)?;
    Ok(())
}
