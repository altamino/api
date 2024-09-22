from numpy.random import randint as randmanyints
from PIL import Image, ImageDraw, ImageFont
from random import randint, choices
from string import digits
from typing import Union
from io import BytesIO
from time import time
import numpy as np
import cv2


class ImageTools:
    """
    TODO:
    - rewrite this crap
    - ImageTools -> CaptchaProcessor and JPEGProcessor
        (image compress processor + converting non-gifs to jpeg processors)
    """

    @staticmethod
    def compress(
        image_bytes: Union[str, bytes],
        image_type: Union[str, None] = None,
        max_size: int = 1024,
    ):
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if not image_type:
            if img.shape[2] == 3:
                image_type = "jpg"
            elif img.shape[2] == 4:
                image_type = "png"
            else:
                raise ValueError("Unknown image type")

        if image_type in ["jpg", "jpeg"]:
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 30]
        elif image_type == "png":
            encode_params = [int(cv2.IMWRITE_PNG_COMPRESSION), 7]
        elif image_type == "webp":
            encode_params = [int(cv2.IMWRITE_WEBP_QUALITY), 30]
        elif image_type == "gif":
            return image_bytes
        else:
            raise ValueError("Unsupported image type")

        max_side = max(img.shape[:2])
        if max_side > max_size:
            scale_factor = max_size / max_side
            new_size = (
                int(img.shape[1] * scale_factor),
                int(img.shape[0] * scale_factor),
            )
            img = cv2.resize(img, new_size, interpolation=cv2.INTER_LINEAR)

        _, compressed_img = cv2.imencode("." + image_type, img, encode_params)

        return compressed_img.tobytes()

    @staticmethod
    def generate_captcha(
        code: Union[str, None] = None,
        width: int = 500,
        height: int = 100,
        bg_color: tuple = None,
        text_color: tuple = None,
    ):
        t0 = time()

        code_chars = list(code) if code else choices(digits, k=6)
        if not bg_color:
            bg_color = (randint(0, 256), randint(0, 256), randint(0, 256))
        if not text_color:
            text_color = (255 - bg_color[0], 255 - bg_color[1], 255 - bg_color[2])

        image = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(image)

        font = ImageFont.truetype("./files/fonts/{}.ttf".format(randint(1, 7)), 100)

        _ = randmanyints(-5, 5, size=(len(code_chars), 2))
        __ = randmanyints(70, 80, size=len(code_chars))
        ___ = randmanyints(-10, 20, size=(len(code_chars), 2))
        for i, c in enumerate(code_chars):
            x = abs(___[i][0]) + i * __[i] + abs(_[i][0])
            y = ___[i][1] + _[i][1]
            draw.text((x, y), c, font=font, fill=text_color)

        line_count = randint(20, 40)
        x = randmanyints(0, width, size=(line_count, 2))
        y = randmanyints(0, height, size=(line_count, 2))
        fill = randmanyints(0, 255, size=(line_count, 3))
        boldness = randmanyints(2, 4, size=line_count)
        for i in range(line_count):
            draw.line(
                (x[i][0], y[i][0], x[i][1], y[i][1]),
                fill=tuple(fill[i]),
                width=boldness[i],
            )

        r = BytesIO()
        image.save(r, "JPEG")
        r.seek(0)
        return r, "".join(code_chars), time() - t0
