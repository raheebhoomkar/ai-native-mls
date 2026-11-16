from app.core.config import get_settings
from app.modules.ai.gemini import GeminiVisionProvider
from app.modules.ai.providers import DemoVisionProvider, VisionProvider


def get_provider() -> VisionProvider:
    """Gemini when a key is set; otherwise the demo adapter, whose output says it is demo."""
    settings = get_settings()
    if settings.gemini_api_key is None:
        return DemoVisionProvider()
    return GeminiVisionProvider(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.ai_timeout_seconds,
    )
