# -*- coding: utf-8 -*-

"""Legacy compatibility module.

Production code should import APP.CLIENT.Client_Window instead.
"""

from APP.CLIENT.Client_Window import ClientWindow
from APP.CLIENT.Client_Window import main


TestWindow = ClientWindow
