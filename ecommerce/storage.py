"""
ecommerce/storage.py
────────────────────
Custom static files storage that silently skips missing sourcemap
files (.map) instead of crashing collectstatic.

Why manifest_strict = False isn't enough:
  Whitenoise raises its own MissingFileError during url_converter()
  before Django's manifest_strict check ever runs. We must override
  url_converter() directly to catch and skip the missing files.
"""
import logging
from whitenoise.storage import CompressedManifestStaticFilesStorage

try:
    from whitenoise.storage import MissingFileError
except ImportError:
    # Older whitenoise versions use a different exception
    MissingFileError = ValueError

log = logging.getLogger(__name__)


class LynctelStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Extends CompressedManifestStaticFilesStorage to gracefully handle
    missing files (sourcemaps, external fonts, etc.) instead of crashing.

    When a referenced file can't be found:
      - Logs a WARNING in Railway logs so you know about it
      - Returns the original unmodified URL (no fingerprinting for that ref)
      - collectstatic continues and succeeds
    """
    manifest_strict = False   # also silence Django's manifest strict mode

    def url_converter(self, name, hashed_files, template=None):
        # Get the original converter function from Whitenoise
        converter = super().url_converter(name, hashed_files, template)

        def safe_converter(matchobj):
            try:
                return converter(matchobj)
            except (MissingFileError, ValueError, KeyError) as exc:
                # Log a warning but return the original unmodified reference
                log.warning(
                    '[collectstatic] Skipping missing static file referenced in %s: %s',
                    name, exc
                )
                return matchobj.group(0)   # return original unchanged

        return safe_converter