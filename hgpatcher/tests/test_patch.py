import unittest

from patchtool import apply_patch

class PatchTest(unittest.TestCase):
    def _do_test(self, original, patch, expected):
        self.assertEqual(apply_patch(patch, original), expected)

    def test_simple_patch(self):
        self._do_test(**test1_data)

    def test_offset_patch(self):
        self._do_test(**test2_data)

test1_data = {
'original': """\
some text
with important initial
information that is going
to be changed by a
patch in the form of a unified
diff.
""",

'patch': """\
--- 1   2010-01-15 15:01:37.000000000 +0200
+++ 2   2010-01-15 15:01:45.000000000 +0200
@@ -1,6 +1,6 @@
 some text
-with important initial
-information that is going
 to be changed by a
+information that is going
 patch in the form of a unified
 diff.
+with important initial
""",

'expected': """\
some text
to be changed by a
information that is going
patch in the form of a unified
diff.
with important initial
""",
}

test2_data = {
'original': """\
1
2
a
b
c
3
4
5
6
7
8
9
10
11
""",

'patch': """\
--- 1   2010-01-15 15:08:03.000000000 +0200
+++ 2   2010-01-15 15:08:11.000000000 +0200
@@ -6,6 +6,4 @@
 6
 7
 8
-9
-10
 11
""",

'expected': """\
1
2
a
b
c
3
4
5
6
7
8
11
""",
}
