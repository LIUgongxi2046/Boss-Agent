import os
import sys

from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup

begin_source_cleanup(ControlStore(sys.argv[1]), "ui-check", "finance-note", "1")
os._exit(17)
