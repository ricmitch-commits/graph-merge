class VertexClient:
    """Google Vertex AI client.

    Authentication: run `gcloud auth application-default login` or set
    GOOGLE_APPLICATION_CREDENTIALS to a service account key file.
    Set project and location via VERTEX_PROJECT and VERTEX_LOCATION env vars
    (defaults: project from gcloud config, location "us-central1").
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import os
        import vertexai
        from vertexai.generative_models import GenerativeModel

        project = os.environ.get("VERTEX_PROJECT")
        location = os.environ.get("VERTEX_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)

        model = GenerativeModel(self._model_id)
        response = model.generate_content(prompt)
        return response.text
