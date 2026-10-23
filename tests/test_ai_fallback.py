import os
import unittest
from unittest.mock import AsyncMock, patch

from backend import ai_service


class RecommendationFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_preserves_rules(self):
        base = [{"action": "Add README"}]
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}), \
             patch.object(ai_service, "_request_recommendations", new=AsyncMock()) as request:
            response = await ai_service.generate_ai_recommendations_list("owner", "repo", base)
        request.assert_not_awaited()
        self.assertIsNone(response["model"])
        self.assertEqual(response["recommendations"], base)

    async def test_invalid_output_and_provider_errors_fall_back(self):
        base = [{"action": "Add README"}]
        for invalid in [None, [], {"summary": "ok", "recommendations": "wrong"},
                        {"summary": "ok", "recommendations": [{"title": [1]}]},
                        {"summary": "ok", "recommendations": [{}]}]:
            with self.subTest(invalid=invalid), patch.dict(os.environ, {"GROQ_API_KEY": "test"}), \
                 patch.object(ai_service, "_request_recommendations", new=AsyncMock(return_value=invalid)):
                response = await ai_service.generate_ai_recommendations_list("owner", "repo", base)
            self.assertIsNone(response["model"])
            self.assertEqual(response["recommendations"], base)
        with patch.dict(os.environ, {"GROQ_API_KEY": "test"}), \
             patch.object(ai_service, "_request_recommendations", new=AsyncMock(side_effect=TimeoutError)):
            response = await ai_service.generate_ai_recommendations_list("owner", "repo", base)
        self.assertIsNone(response["model"])

    async def test_valid_generation_reports_model(self):
        result = {"summary": "Useful summary", "recommendations": [{"title": "Add README", "action": "Write it"}]}
        with patch.dict(os.environ, {"GROQ_API_KEY": "test"}), \
             patch.object(ai_service, "_request_recommendations", new=AsyncMock(return_value=result)):
            response = await ai_service.generate_ai_recommendations_list("owner", "repo", [])
        self.assertEqual(response["model"], ai_service.MODEL_NAME)
        self.assertEqual(response["recommendations"], result["recommendations"])


if __name__ == "__main__":
    unittest.main()
