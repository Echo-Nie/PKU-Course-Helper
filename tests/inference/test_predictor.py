import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


class InferenceTests(unittest.TestCase):
    def test_decoder_preserves_blank_separated_repetitions(self):
        from autoelective.inference import decode_ctc
        logits = np.full((5, 3), -20.0)
        logits[np.arange(5), [0, 0, 2, 0, 1]] = 20.0
        self.assertEqual(decode_ctc(logits), [0, 0, 1])

    def test_beam_is_not_greedy(self):
        from autoelective.inference import decode_ctc
        # Retaining the existing prefix combines repeated-label and blank paths.
        logits = np.log([[0.6, 0.1, 0.3], [0.3, 0.4, 0.3]])
        self.assertEqual(decode_ctc(logits), [0])

    def test_preprocessing_shape_color_and_range(self):
        from autoelective.inference import preprocess
        stream = io.BytesIO()
        Image.new('RGB', (130, 52), (255, 0, 128)).save(stream, format='PNG')
        result = preprocess(stream.getvalue())
        self.assertEqual(result.shape, (1, 130, 52, 3))
        self.assertEqual(result.dtype, np.float32)
        np.testing.assert_allclose(result[0, 0, 0], [1.0, 0.0, 128 / 255])

    def test_invalid_image_is_rejected(self):
        from autoelective.inference import preprocess
        with self.assertRaises(ValueError):
            preprocess(b'not an image')

    def test_corrupted_model_fails_integrity_check(self):
        from autoelective.inference import OnnxPredictor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text(json.dumps({'sha256': '0' * 64}), encoding='utf-8')
            (root / 'captcha.onnx').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                OnnxPredictor(root).startSession()

    def test_float_resize_uses_half_pixel_coordinates(self):
        from autoelective.inference.predictor import _resize_linear
        source = np.array([[[0, 0, 0], [100, 100, 100]]], dtype=np.float32)
        result = _resize_linear(source, 4, 1)
        np.testing.assert_array_equal(result[0, :, 0], [0, 25, 75, 100])

    def test_bundled_model_recognizes_all_fixtures(self):
        from autoelective.inference import OnnxPredictor
        predictor = OnnxPredictor()
        files = sorted((Path(__file__).resolve().parent / 'data').glob('*.jpg'))
        self.assertEqual(len(files), 20)
        for path in files:
            with self.subTest(path=path.name):
                self.assertEqual(predictor.predictOneCaptcha(path.read_bytes()), path.stem.split('_')[0])
        self.assertEqual(predictor.predictOneCaptcha(b''), '')
        predictor.closeSession()


if __name__ == '__main__':
    unittest.main()
