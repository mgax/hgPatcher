from StringIO import StringIO
import patch

def apply_patch(the_patch, original_str):
    targetfile = StringIO(original_str)
    changed = {}
    patch.applydiff_hacked(the_patch, targetfile, changed)
    return targetfile.getvalue()
