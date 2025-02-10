"""Initialize appliers and register them with the factory."""

from app.appliers.factory import JobApplierFactory
from app.appliers.seek import SeekApplier

# Register appliers
JobApplierFactory.register_applier("seek", SeekApplier)
