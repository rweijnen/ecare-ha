DOMAIN = "ecare"

IDP_BASE       = "https://pvj-idp.ecare.nl"
CLIENT_ID      = "PuurVanJouWijkzorg"
REDIRECT_URI   = "https://wijkzorg.puurvanjou.nl/silent-refresh.html"
PORTAL_BASE    = "https://wijkzorg.puurvanjou.nl"
SCOPE          = "openid profile roles"

CONF_EMAIL     = "email"
CONF_PASSWORD  = "password"
CONF_COOKIES   = "cookies"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 15  # minuten

STATE_FILE_KEY = "known_event_ids"
