# services/embedding_service.py

import base64
from io import BytesIO

import torch
from PIL import Image

from models.clip import (
    model,
    preprocess,
    tokenizer,
    DEVICE
)


def base64_to_image(base64_string):
    """
    Convert Base64 string to PIL Image
    """

    # Remove data:image/...;base64, if present
    if "," in base64_string:
        base64_string = base64_string.split(",", 1)[1]

    image_bytes = base64.b64decode(base64_string)

    image = Image.open(
        BytesIO(image_bytes)
    ).convert("RGB")

    return image


def get_image_embedding_from_base64(base64_string):
    """
    Generate image embedding from Base64 image
    """

    image = base64_to_image(base64_string)

    image_tensor = (
        preprocess(image)
        .unsqueeze(0)
        .to(DEVICE)
    )

    with torch.no_grad():
        embedding = model.encode_image(
            image_tensor
        )

        # Normalize vector
        embedding = embedding / embedding.norm(
            dim=-1,
            keepdim=True
        )

    return embedding.cpu().numpy()[0].tolist()


def get_text_embedding(text):
    """
    Generate embedding from text
    """

    text_tokens = tokenizer([text]).to(DEVICE)

    with torch.no_grad():
        embedding = model.encode_text(
            text_tokens
        )

        embedding = embedding / embedding.norm(
            dim=-1,
            keepdim=True
        )

    return embedding.cpu().numpy()[0].tolist()
