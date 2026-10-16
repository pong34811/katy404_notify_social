from django.core.validators import RegexValidator

channel_id_validator = RegexValidator(r"\AUC[A-Za-z0-9_-]{22}\Z", "Invalid channel ID")
video_id_validator = RegexValidator(r"\A[A-Za-z0-9_-]{11}\Z", "Invalid video ID")
page_id_validator = RegexValidator(r"\A[0-9]+\Z", "Invalid Page ID")
token_env_validator = RegexValidator(
    r"\AFB_PAGE_TOKEN_[A-Z0-9_]+\Z", "Invalid token environment name"
)
