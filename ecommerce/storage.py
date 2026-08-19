from whitenoise.storage import CompressedManifestStaticFilesStorage


class LynctelStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Extends Whitenoise storage with manifest_strict=False so missing
    sourcemap files (.map) and broken @import references don't crash
    collectstatic — they get a warning instead.
    """
    manifest_strict = False