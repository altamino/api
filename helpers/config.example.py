class Config:
    MONGODB_CONNECTION_STRING = "mongodb://127.0.0.1"
    MONGODB_MAIN_DB = "global"

    REDIS_CONNECTION_STRING = "redis://127.0.0.1"

    S3_SERVICE_NAME = "s3"
    S3_ACCESS_KEY = ""
    S3_SECRET_ACCESS_KEY = ""
    S3_ENDPOINT_URL = ""
    S3_BUCKET_NAME = "media.altamino.top"
    MEDIA_BASE_URL = "https://media.altamino.top/"

    MAX_FILE_SIZE = 5242880
    MAX_TEXT_SIZE = 2345

    SMTP_SERVER = "...altamino.top"
    SMTP_PORT = 587
    SMTP_USER = "service@altamino.top"
    SMTP_PSWD = ""

    API_DOMAIN = "https://service.altamino.top"
    SITE_DOMAIN = "http://altamino.top"

    WS_LINK = "ws://127.0.0.1:8081"
    WS_ADMIN_KEY = ""
    WS_ADMIN_VERIFY = ""
