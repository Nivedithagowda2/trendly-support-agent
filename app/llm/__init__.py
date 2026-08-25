from app import config
from app.llm.base import LLMProvider

_provider_instance: LLMProvider = None


def get_provider() -> LLMProvider:
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    if config.LLM_PROVIDER == "groq":
        from app.llm.groq_provider import GroqProvider

        _provider_instance = GroqProvider()
    elif config.LLM_PROVIDER == "gemini":
        from app.llm.gemini_provider import GeminiProvider

        _provider_instance = GeminiProvider()
    else:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{config.LLM_PROVIDER}'. Use 'groq' or 'gemini'."
        )
    return _provider_instance
