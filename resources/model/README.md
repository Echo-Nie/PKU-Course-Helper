# Portable captcha model

`captcha.onnx` contains only inference weights and operators from the existing
`recognizer_v11-CNN5-GRU-H128-CTC-C1.model-57000` checkpoint. No retraining,
quantization, or checkpoint substitution was performed. The file is about
2.9 MiB; the desktop distribution excludes TensorFlow, OpenCV, training code,
and historical checkpoints.

`manifest.json` records source/checkpoint hashes, the model hash, input and
output names, alphabet (including empty symbols), preprocessing and decoding.
The runtime verifies the model hash before creating a CPU-only session.

The original training and export code is available in the upstream
[Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026)
repository. This desktop-focused fork keeps the exported ONNX model,
`manifest.json`, `comparison.json`, and the original model [LICENSE](LICENSE).
The 20 offline recognition fixtures are in `tests/inference/data`.

Run regression checks in the desktop build environment:

```powershell
.venv-desktop/Scripts/python.exe -m pytest tests/inference -q
```

The decoding contract is TensorFlow's CTC prefix beam search with width 1,
not greedy argmax. Its recurrence is documented in the upstream
[TensorFlow implementation](https://github.com/tensorflow/tensorflow/blob/v2.12.0/tensorflow/core/util/ctc/ctc_beam_search.h).
The last of 23 output logits is the CTC blank; category 0 and category 21 both
render as empty strings. Repeated characters separated by a blank are retained.

Keep the repository and upstream model license notices in distributed software.
