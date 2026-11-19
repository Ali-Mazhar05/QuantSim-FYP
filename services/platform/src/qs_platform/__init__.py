"""QuantSim M0: platform and identity.

Owns users and roles (``platform_db``), signs every access token, publishes the public
keys other services verify tokens with, and cuts off tokens when a user is deactivated or
their role changes (FR-PLT-001..008).
"""
