hgPatcher
=========

hgPatcher is code from Mercurial, stripped and hacked. Its purpose is to
apply patches, in `unified diff` format, to in-memory strings. For now
it can only handle patches that change a single file. The code is liable
to break in interesting ways, but it should not touch anything on-disk,
so it's safe to use in a try-except block::

    >>> try:
    ...     import hgpatcher
    ...     out_str = hgpatcher(patch_str, in_str)
    ... except Exception, e:
    ...     print "patch failed: %r" % e
    ... else:
    ...     print out_str
