from os import environ


class Config:
    """
    Config class that contains all configuration variables from ENV.
    """

    # static values
    LANG_SEGMENTS = ["en", "ru", "es", "ar", "pt", "zh-Hans"]

    # database connection settings (required)
    REDIS_CONNECTION_STRING = environ.get("REDIS_CONNECTION_STRING")
    MONGODB_CONNECTION_STRING = environ.get("MONGODB_CONNECTION_STRING")
    MONGODB_MAIN_DB = environ.get("MONGODB_MAIN_DB")

    # s3 settings (required)
    S3_SERVICE_NAME = environ.get("S3_SERVICE_NAME")
    S3_ACCESS_KEY = environ.get("S3_ACCESS_KEY")
    S3_SECRET_ACCESS_KEY = environ.get("S3_SECRET_ACCESS_KEY")
    S3_ENDPOINT_URL = environ.get("S3_ENDPOINT_URL")
    S3_BUCKET_NAME = environ.get("S3_BUCKET_NAME")
    MEDIA_BASE_URL = environ.get("MEDIA_BASE_URL")
    # i think it can be static
    # why you need to change them?
    S3_UPLOADS_FOLDER = "user-uploads/"
    S3_IMAGES_FOLDER = S3_UPLOADS_FOLDER + "images/"
    S3_VOICES_FOLDER = S3_UPLOADS_FOLDER + "voices/"
    S3_NDCTHEMES_FOLDER = "ndc-themes/"
    S3_STORE_FOLDER = "store-resources/"

    # maximums settings (optional to configure)
    MAX_FILE_SIZE = int(environ.get("MAX_FILE_SIZE", 5000000))
    MAX_TEXT_SIZE = int(environ.get("MAX_TEXT_SIZE", 2000))

    # email settings (optional but required if ENABLE_EMAIL is True and if its prod server)
    ENABLE_EMAIL = bool(
        environ.get("ENABLE_EMAIL", 1)
    )  # if disabled, any code can be used + no email will be sended
    SMTP_SERVER = environ.get("SMTP_SERVER")
    SMTP_PORT = environ.get("SMTP_PORT")
    SMTP_USER = environ.get("SMTP_USER")
    SMTP_PSWD = environ.get("SMTP_PSWD")
    SMTP_SNDR = environ.get("SMTP_SNDR")
    # [WARNING]
    # might be deprecated soon since mostly we use default ports in the internet
    # for now it's here for backward compatibility and to avoid breaking changes
    SMTP_STARTTLS = environ.get("SMTP_STARTTLS", "true").lower() in ["true", "1"]
    SMTP_SSL = environ.get("SMTP_SSL", "").lower() in ["true", "1"]

    # aquarium encryption keys (required)
    AETHER_KEY = environ.get("AETHER_KEY")  # optional
    FISH_KEY = environ.get("FISH_KEY")  # optional
    FERNET_KEY = environ.get("FERNET_KEY")
    PASSWORD_SALT = environ.get("PASSWORD_SALT")

    # domains and url (required)
    API_DOMAIN = environ.get("API_DOMAIN")
    API_BASE_URL = environ.get("API_BASE_URL", f"https://{API_DOMAIN}")
    SITE_DOMAIN = environ.get("SITE_DOMAIN")
    SITE_BASE_URL = environ.get("SITE_BASE_URL", f"https://{SITE_DOMAIN}")

    # websocket settings (optional for dev env, required for prod env)
    WS_LINK = environ.get("WS_LINK")
    WS_ADMIN_KEY = environ.get("WS_ADMIN_KEY")
    WS_ADMIN_VERIFY = environ.get("WS_ADMIN_VERIFY")

    # turtlelimit (optional but by default enabled)
    ENABLE_TURTLELIMIT = environ.get("ENABLE_TURTLELIMIT", 1)
    TURNSTILE_TOKEN = environ.get("TURNSTILE_TOKEN")

    # bbnonsfw (optional but by default disabled)
    ENABLE_BBNONSFW = environ.get("ENABLE_BBNONSFW", 0)
    BBNONSFW_API_KEY = environ.get("BBNONSFW_API_KEY")
    BBNONSFW_API_URL = environ.get("BBNONSFW_API_URL")

    # bbnospam (optional but by default disabled)
    # not implemented yet but in future will, so.. just boilerplate code
    ENABLE_BBNOSPAM = environ.get("ENABLE_BBNOSPAM", 0)
    BBNOSPAM_API_KEY = environ.get("BBNOSPAM_API_KEY")
    BBNOSPAM_API_URL = environ.get("BBNOSPAM_API_URL")

    # FCM push notifications (optional but by default disabled)
    ENABLE_PUSH = environ.get("ENABLE_PUSH", 0)
    FCM_SERVICE_ACCOUNT = environ.get("FCM_SERVICE_ACCOUNT")

    AGORA_ADMIN_ONLY_MODE = environ.get("AGORA_ADMIN_ONLY_MODE", "0") == "1"