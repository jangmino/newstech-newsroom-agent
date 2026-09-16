from google import genai
from google.genai import types


class GeminiProvider:
    """Create a Gemini client without leaking provider details into the orchestrator."""

    def __init__(
        self,
        *,
        auth_mode: str,
        api_key: str = "",
        project: str = "",
        location: str = "asia-northeast3",
        http_options: types.HttpOptions | None = None,
    ) -> None:
        if auth_mode == "api_key":
            if not api_key:
                raise ValueError("GEMINI_API_KEY is required for api_key mode")
            self.client = genai.Client(vertexai=False, api_key=api_key, http_options=http_options)
        elif auth_mode == "vertex_ai":
            if not project:
                raise ValueError("GOOGLE_CLOUD_PROJECT is required for vertex_ai mode")
            self.client = genai.Client(
                vertexai=True, project=project, location=location, http_options=http_options,
            )
        else:
            raise ValueError(f"Unsupported GEMINI_AUTH_MODE: {auth_mode}")
