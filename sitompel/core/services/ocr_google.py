import os
import io
import base64
from pathlib import Path

from django.conf import settings
from google.cloud import vision
import requests


def _cari_file_kredensial_google():
    credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    kandidat_path = [
        Path(credential_path) if credential_path else None,
        settings.BASE_DIR / "kredensial-gcp.json",
        settings.BASE_DIR.parent / "kredensial-gcp.json",
    ]

    for path in kandidat_path:
        if path and path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path.resolve())
            return True

    return False


def _ekstrak_teks_dengan_api_key(path_gambar_absolut, api_key):
    with io.open(path_gambar_absolut, 'rb') as image_file:
        encoded_content = base64.b64encode(image_file.read()).decode('utf-8')

    response = requests.post(
        "https://vision.googleapis.com/v1/images:annotate",
        params={"key": api_key},
        json={
            "requests": [
                {
                    "image": {"content": encoded_content},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }
            ]
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    annotation = data.get("responses", [{}])[0]

    if annotation.get("error"):
        raise Exception(f"Google Vision API Error: {annotation['error'].get('message', annotation['error'])}")

    return annotation.get("fullTextAnnotation", {}).get("text", "")

def ekstrak_teks_dari_gambar(path_gambar_absolut):
    """
    Mengirim gambar ke Google Cloud Vision API dan mengembalikan teksnya.
    """
    api_key = os.environ.get("GOOGLE_VISION_API_KEY") or getattr(settings, "GOOGLE_VISION_API_KEY", "")

    if api_key:
        return _ekstrak_teks_dengan_api_key(path_gambar_absolut, api_key)

    has_credential_file = _cari_file_kredensial_google()
    if not has_credential_file and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        # Biarkan client library mencoba Application Default Credentials, misalnya dari
        # `gcloud auth application-default login`.
        pass

    client = vision.ImageAnnotatorClient()

    with io.open(path_gambar_absolut, 'rb') as image_file:
        content = image_file.read()

    image = vision.Image(content=content)
    
    # Memanggil fitur Document Text Detection (khusus untuk tulisan tangan/dokumen padat)
    response = client.document_text_detection(image=image)
    
    if response.error.message:
        raise Exception(f'Google Vision API Error: {response.error.message}')
        
    # Mengambil seluruh teks yang terdeteksi secara utuh
    if response.full_text_annotation:
        return response.full_text_annotation.text
    
    return ""
