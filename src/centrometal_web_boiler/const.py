"""Addresses of the Centrometal cloud (web-boiler.com).

The library talks to two services:
- the website, over HTTPS: login, reading the configuration, sending commands;
- a STOMP message broker over a secure WebSocket: real-time parameter values.
"""

# Website (HTTPS)
WEB_BOILER_WEBROOT = "https://www.web-boiler.com"

# Real-time broker (STOMP over WebSocket). The credentials are the generic ones used by the
# Centrometal web application; the user account is only used for the HTTPS login.
WEB_BOILER_STOMP_URL = "wss://web-boiler.com:15671/ws"
WEB_BOILER_STOMP_LOGIN_USERNAME = "appuser"
WEB_BOILER_STOMP_LOGIN_PASSCODE = "appuser"
# Heart-beats announced to the broker, in milliseconds: (client sends every, client expects every)
WEB_BOILER_STOMP_HEARTBEATS = (90000, 60000)

# One topic per boiler: /topic/cm.inst.<type>.<serial>
WEB_BOILER_STOMP_DEVICE_TOPIC = "/topic/cm.inst."
WEB_BOILER_STOMP_NOTIFICATION_TOPIC = "/queue/notification"
