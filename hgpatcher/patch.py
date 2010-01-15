# patch.py - patch file parsing routines
#
# Copyright 2006 Brendan Cully <brendan@kublai.com>
# Copyright 2007 Chris Mason <chris.mason@oracle.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import diffhelpers
import cStringIO, re
import zlib
_ = lambda s: s

gitre = re.compile('diff --git a/(.*) b/(.*)')

class PatchError(Exception):
    pass

class NoHunks(PatchError):
    pass

# helper functions

# public functions

GP_PATCH  = 1 << 0  # we have to run patch
GP_FILTER = 1 << 1  # there's some copy/rename operation
GP_BINARY = 1 << 2  # there's a binary patch

class patchmeta(object):
    """Patched file metadata

    'op' is the performed operation within ADD, DELETE, RENAME, MODIFY
    or COPY.  'path' is patched file path. 'oldpath' is set to the
    origin file when 'op' is either COPY or RENAME, None otherwise. If
    file mode is changed, 'mode' is a tuple (islink, isexec) where
    'islink' is True if the file is a symlink and 'isexec' is True if
    the file is executable. Otherwise, 'mode' is None.
    """
    def __init__(self, path):
        self.path = path
        self.oldpath = None
        self.mode = None
        self.op = 'MODIFY'
        self.lineno = 0
        self.binary = False

    def setmode(self, mode):
        islink = mode & 020000
        isexec = mode & 0100
        self.mode = (islink, isexec)

def readgitpatch(lr):
    """extract git-style metadata about patches from <patchname>"""

    # Filter patch for git information
    gp = None
    gitpatches = []
    # Can have a git patch with only metadata, causing patch to complain
    dopatch = 0

    lineno = 0
    for line in lr:
        lineno += 1
        line = line.rstrip(' \r\n')
        if line.startswith('diff --git'):
            m = gitre.match(line)
            if m:
                if gp:
                    gitpatches.append(gp)
                dst = m.group(2)
                gp = patchmeta(dst)
                gp.lineno = lineno
        elif gp:
            if line.startswith('--- '):
                if gp.op in ('COPY', 'RENAME'):
                    dopatch |= GP_FILTER
                gitpatches.append(gp)
                gp = None
                dopatch |= GP_PATCH
                continue
            if line.startswith('rename from '):
                gp.op = 'RENAME'
                gp.oldpath = line[12:]
            elif line.startswith('rename to '):
                gp.path = line[10:]
            elif line.startswith('copy from '):
                gp.op = 'COPY'
                gp.oldpath = line[10:]
            elif line.startswith('copy to '):
                gp.path = line[8:]
            elif line.startswith('deleted file'):
                gp.op = 'DELETE'
                # is the deleted file a symlink?
                gp.setmode(int(line[-6:], 8))
            elif line.startswith('new file mode '):
                gp.op = 'ADD'
                gp.setmode(int(line[-6:], 8))
            elif line.startswith('new mode '):
                gp.setmode(int(line[-6:], 8))
            elif line.startswith('GIT binary patch'):
                dopatch |= GP_BINARY
                gp.binary = True
    if gp:
        gitpatches.append(gp)

    if not gitpatches:
        dopatch = GP_PATCH

    return (dopatch, gitpatches)

class linereader(object):
    # simple class to allow pushing lines back into the input stream
    def __init__(self, fp, textmode=False):
        self.fp = fp
        self.buf = []
        self.textmode = textmode

    def push(self, line):
        if line is not None:
            self.buf.append(line)

    def readline(self):
        if self.buf:
            l = self.buf[0]
            del self.buf[0]
            return l
        l = self.fp.readline()
        if self.textmode and l.endswith('\r\n'):
            l = l[:-2] + '\n'
        return l

    def __iter__(self):
        while 1:
            l = self.readline()
            if not l:
                break
            yield l

# @@ -start,len +start,len @@ or @@ -start +start @@ if len is 1
unidesc = re.compile('@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@')
contextdesc = re.compile('(---|\*\*\*) (\d+)(,(\d+))? (---|\*\*\*)')

class patchfile(object):
    def __init__(self, ui, fname, targetfile, missing=False, eol=None):
        self.fname = fname
        self.eol = eol
        self.targetfile = targetfile
        self.ui = ui
        self.lines = list(linereader(targetfile, self.eol is not None))
        if missing is not False:
            raise NotImplementedError

        self.hash = {}
        self.dirty = 0
        self.offset = 0
        self.skew = 0
        self.rej = []
        self.fileprinted = False
        self.printfile(False)
        self.hunks = 0
        self.missing = False

    def writelines(self, fname, lines):
        fp = cStringIO.StringIO()
        try:
            if self.eol and self.eol != '\n':
                for l in lines:
                    if l and l[-1] == '\n':
                        l = l[:-1] + self.eol
                    fp.write(l)
            else:
                fp.writelines(lines)
            self.targetfile.seek(0)
            self.targetfile.truncate()
            self.targetfile.write(fp.getvalue())
        finally:
            fp.close()

    def unlink(self, fname):
        raise NotImplementedError

    def printfile(self, warn):
        if self.fileprinted:
            return
        if warn or self.ui.verbose:
            self.fileprinted = True
        s = _("patching file %s\n") % self.fname
        if warn:
            self.ui.warn(s)
        else:
            self.ui.note(s)


    def findlines(self, l, linenum):
        # looks through the hash and finds candidate lines.  The
        # result is a list of line numbers sorted based on distance
        # from linenum

        cand = self.hash.get(l, [])
        if len(cand) > 1:
            # resort our list of potentials forward then back.
            cand.sort(key=lambda x: abs(x - linenum))
        return cand

    def hashlines(self):
        self.hash = {}
        for x, s in enumerate(self.lines):
            self.hash.setdefault(s, []).append(x)

    def write_rej(self):
        if self.rej:
            raise NotImplementedError

    def write(self, dest=None):
        if not self.dirty:
            return
        if dest is not None:
            raise NotImplementedError
        self.writelines(self.fname, self.lines)

    def close(self):
        self.write()
        self.write_rej()

    def apply(self, h):
        if not h.complete():
            raise PatchError(_("bad hunk #%d %s (%d %d %d %d)") %
                            (h.number, h.desc, len(h.a), h.lena, len(h.b),
                            h.lenb))

        self.hunks += 1

        if self.missing:
            self.rej.append(h)
            return -1

        if h.createfile():
            raise NotImplementedError

        # fast case first, no offsets, no fuzz
        old = h.old()
        # patch starts counting at 1 unless we are adding the file
        if h.starta == 0:
            start = 0
        else:
            start = h.starta + self.offset - 1
        orig_start = start
        # if there's skew we want to emit the "(offset %d lines)" even
        # when the hunk cleanly applies at start + skew, so skip the
        # fast case code
        if self.skew == 0 and diffhelpers.testhunk(old, self.lines, start) == 0:
            if h.rmfile():
                self.unlink(self.fname)
            else:
                self.lines[start : start + h.lena] = h.new()
                self.offset += h.lenb - h.lena
                self.dirty = 1
            return 0

        # ok, we couldn't match the hunk.  Lets look for offsets and fuzz it
        self.hashlines()
        if h.hunk[-1][0] != ' ':
            # if the hunk tried to put something at the bottom of the file
            # override the start line and use eof here
            search_start = len(self.lines)
        else:
            search_start = orig_start + self.skew

        for fuzzlen in xrange(3):
            for toponly in [ True, False ]:
                old = h.old(fuzzlen, toponly)

                cand = self.findlines(old[0][1:], search_start)
                for l in cand:
                    if diffhelpers.testhunk(old, self.lines, l) == 0:
                        newlines = h.new(fuzzlen, toponly)
                        self.lines[l : l + len(old)] = newlines
                        self.offset += len(newlines) - len(old)
                        self.skew = l - orig_start
                        self.dirty = 1
                        if fuzzlen:
                            fuzzstr = "with fuzz %d " % fuzzlen
                            f = self.ui.warn
                            self.printfile(True)
                        else:
                            fuzzstr = ""
                            f = self.ui.note
                        offset = l - orig_start - fuzzlen
                        if offset == 1:
                            msg = _("Hunk #%d succeeded at %d %s"
                                    "(offset %d line).\n")
                        else:
                            msg = _("Hunk #%d succeeded at %d %s"
                                    "(offset %d lines).\n")
                        f(msg % (h.number, l+1, fuzzstr, offset))
                        return fuzzlen
        self.printfile(True)
        self.ui.warn(_("Hunk #%d FAILED at %d\n") % (h.number, orig_start))
        self.rej.append(h)
        return -1

class hunk(object):
    def __init__(self, desc, num, lr, context, create=False, remove=False):
        self.number = num
        self.desc = desc
        self.hunk = [ desc ]
        self.a = []
        self.b = []
        self.starta = self.lena = None
        self.startb = self.lenb = None
        if context:
            self.read_context_hunk(lr)
        else:
            self.read_unified_hunk(lr)
        self.create = create
        self.remove = remove and not create

    def read_unified_hunk(self, lr):
        m = unidesc.match(self.desc)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        self.starta, foo, self.lena, self.startb, foo2, self.lenb = m.groups()
        if self.lena is None:
            self.lena = 1
        else:
            self.lena = int(self.lena)
        if self.lenb is None:
            self.lenb = 1
        else:
            self.lenb = int(self.lenb)
        self.starta = int(self.starta)
        self.startb = int(self.startb)
        diffhelpers.addlines(lr, self.hunk, self.lena, self.lenb, self.a, self.b)
        # if we hit eof before finishing out the hunk, the last line will
        # be zero length.  Lets try to fix it up.
        while len(self.hunk[-1]) == 0:
            del self.hunk[-1]
            del self.a[-1]
            del self.b[-1]
            self.lena -= 1
            self.lenb -= 1

    def read_context_hunk(self, lr):
        self.desc = lr.readline()
        m = contextdesc.match(self.desc)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        foo, self.starta, foo2, aend, foo3 = m.groups()
        self.starta = int(self.starta)
        if aend is None:
            aend = self.starta
        self.lena = int(aend) - self.starta
        if self.starta:
            self.lena += 1
        for x in xrange(self.lena):
            l = lr.readline()
            if l.startswith('---'):
                lr.push(l)
                break
            s = l[2:]
            if l.startswith('- ') or l.startswith('! '):
                u = '-' + s
            elif l.startswith('  '):
                u = ' ' + s
            else:
                raise PatchError(_("bad hunk #%d old text line %d") %
                                 (self.number, x))
            self.a.append(u)
            self.hunk.append(u)

        l = lr.readline()
        if l.startswith('\ '):
            s = self.a[-1][:-1]
            self.a[-1] = s
            self.hunk[-1] = s
            l = lr.readline()
        m = contextdesc.match(l)
        if not m:
            raise PatchError(_("bad hunk #%d") % self.number)
        foo, self.startb, foo2, bend, foo3 = m.groups()
        self.startb = int(self.startb)
        if bend is None:
            bend = self.startb
        self.lenb = int(bend) - self.startb
        if self.startb:
            self.lenb += 1
        hunki = 1
        for x in xrange(self.lenb):
            l = lr.readline()
            if l.startswith('\ '):
                s = self.b[-1][:-1]
                self.b[-1] = s
                self.hunk[hunki-1] = s
                continue
            if not l:
                lr.push(l)
                break
            s = l[2:]
            if l.startswith('+ ') or l.startswith('! '):
                u = '+' + s
            elif l.startswith('  '):
                u = ' ' + s
            elif len(self.b) == 0:
                # this can happen when the hunk does not add any lines
                lr.push(l)
                break
            else:
                raise PatchError(_("bad hunk #%d old text line %d") %
                                 (self.number, x))
            self.b.append(s)
            while True:
                if hunki >= len(self.hunk):
                    h = ""
                else:
                    h = self.hunk[hunki]
                hunki += 1
                if h == u:
                    break
                elif h.startswith('-'):
                    continue
                else:
                    self.hunk.insert(hunki-1, u)
                    break

        if not self.a:
            # this happens when lines were only added to the hunk
            for x in self.hunk:
                if x.startswith('-') or x.startswith(' '):
                    self.a.append(x)
        if not self.b:
            # this happens when lines were only deleted from the hunk
            for x in self.hunk:
                if x.startswith('+') or x.startswith(' '):
                    self.b.append(x[1:])
        # @@ -start,len +start,len @@
        self.desc = "@@ -%d,%d +%d,%d @@\n" % (self.starta, self.lena,
                                             self.startb, self.lenb)
        self.hunk[0] = self.desc

    def fix_newline(self):
        diffhelpers.fix_newline(self.hunk, self.a, self.b)

    def complete(self):
        return len(self.a) == self.lena and len(self.b) == self.lenb

    def createfile(self):
        return self.starta == 0 and self.lena == 0 and self.create

    def rmfile(self):
        return self.startb == 0 and self.lenb == 0 and self.remove

    def fuzzit(self, l, fuzz, toponly):
        # this removes context lines from the top and bottom of list 'l'.  It
        # checks the hunk to make sure only context lines are removed, and then
        # returns a new shortened list of lines.
        fuzz = min(fuzz, len(l)-1)
        if fuzz:
            top = 0
            bot = 0
            hlen = len(self.hunk)
            for x in xrange(hlen-1):
                # the hunk starts with the @@ line, so use x+1
                if self.hunk[x+1][0] == ' ':
                    top += 1
                else:
                    break
            if not toponly:
                for x in xrange(hlen-1):
                    if self.hunk[hlen-bot-1][0] == ' ':
                        bot += 1
                    else:
                        break

            # top and bot now count context in the hunk
            # adjust them if either one is short
            context = max(top, bot, 3)
            if bot < context:
                bot = max(0, fuzz - (context - bot))
            else:
                bot = min(fuzz, bot)
            if top < context:
                top = max(0, fuzz - (context - top))
            else:
                top = min(fuzz, top)

            return l[top:len(l)-bot]
        return l

    def old(self, fuzz=0, toponly=False):
        return self.fuzzit(self.a, fuzz, toponly)

    def newctrl(self):
        res = []
        for x in self.hunk:
            c = x[0]
            if c == ' ' or c == '+':
                res.append(x)
        return res

    def new(self, fuzz=0, toponly=False):
        return self.fuzzit(self.b, fuzz, toponly)

def parsefilename(str):
    # --- filename \t|space stuff
    s = str[4:].rstrip('\r\n')
    i = s.find('\t')
    if i < 0:
        i = s.find(' ')
        if i < 0:
            return s
    return s[:i]

def scangitpatch(lr, firstline):
    """
    Git patches can emit:
    - rename a to b
    - change b
    - copy a to c
    - change c

    We cannot apply this sequence as-is, the renamed 'a' could not be
    found for it would have been renamed already. And we cannot copy
    from 'b' instead because 'b' would have been changed already. So
    we scan the git patch for copy and rename commands so we can
    perform the copies ahead of time.
    """
    pos = 0
    try:
        pos = lr.fp.tell()
        fp = lr.fp
    except IOError:
        fp = cStringIO.StringIO(lr.fp.read())
    gitlr = linereader(fp, lr.textmode)
    gitlr.push(firstline)
    (dopatch, gitpatches) = readgitpatch(gitlr)
    fp.seek(pos)
    return dopatch, gitpatches

def iterhunks(ui, fp, sourcefile=None, textmode=False):
    """Read a patch and yield the following events:
    - ("file", afile, bfile, firsthunk): select a new target file.
    - ("hunk", hunk): a new hunk is ready to be applied, follows a
    "file" event.
    - ("git", gitchanges): current diff is in git format, gitchanges
    maps filenames to gitpatch records. Unique event.

    If textmode is True, input line-endings are normalized to LF.
    """
    changed = {}
    current_hunk = None
    afile = ""
    bfile = ""
    state = None
    hunknum = 0
    emitfile = False
    git = False

    # our states
    BFILE = 1
    context = None
    lr = linereader(fp, textmode)
    dopatch = True
    # gitworkdone is True if a git operation (copy, rename, ...) was
    # performed already for the current file. Useful when the file
    # section may have no hunk.
    gitworkdone = False

    while True:
        newfile = False
        x = lr.readline()
        if not x:
            break
        if current_hunk:
            if x.startswith('\ '):
                current_hunk.fix_newline()
            yield 'hunk', current_hunk
            current_hunk = None
            gitworkdone = False
        if ((sourcefile or state == BFILE) and ((not context and x[0] == '@') or
            ((context is not False) and x.startswith('***************')))):
            try:
                if context is None and x.startswith('***************'):
                    context = True
                gpatch = changed.get(bfile)
                create = afile == '/dev/null' or gpatch and gpatch.op == 'ADD'
                remove = bfile == '/dev/null' or gpatch and gpatch.op == 'DELETE'
                current_hunk = hunk(x, hunknum + 1, lr, context, create, remove)
            except PatchError, err:
                ui.debug(err)
                current_hunk = None
                continue
            hunknum += 1
            if emitfile:
                emitfile = False
                yield 'file', (afile, bfile, current_hunk)
        elif state == BFILE and x.startswith('GIT binary patch'):
            raise NotImplementedError
            current_hunk = binhunk(changed[bfile])
            hunknum += 1
            if emitfile:
                emitfile = False
                yield 'file', ('a/' + afile, 'b/' + bfile, current_hunk)
            current_hunk.extract(lr)
        elif x.startswith('diff --git'):
            # check for git diff, scanning the whole patch file if needed
            m = gitre.match(x)
            if m:
                afile, bfile = m.group(1, 2)
                if not git:
                    git = True
                    dopatch, gitpatches = scangitpatch(lr, x)
                    yield 'git', gitpatches
                    for gp in gitpatches:
                        changed[gp.path] = gp
                # else error?
                # copy/rename + modify should modify target, not source
                gp = changed.get(bfile)
                if gp and gp.op in ('COPY', 'DELETE', 'RENAME', 'ADD'):
                    afile = bfile
                    gitworkdone = True
            newfile = True
        elif x.startswith('---'):
            # check for a unified diff
            l2 = lr.readline()
            if not l2.startswith('+++'):
                lr.push(l2)
                continue
            newfile = True
            context = False
            afile = parsefilename(x)
            bfile = parsefilename(l2)
        elif x.startswith('***'):
            # check for a context diff
            l2 = lr.readline()
            if not l2.startswith('---'):
                lr.push(l2)
                continue
            l3 = lr.readline()
            lr.push(l3)
            if not l3.startswith("***************"):
                lr.push(l2)
                continue
            newfile = True
            context = True
            afile = parsefilename(x)
            bfile = parsefilename(l2)

        if newfile:
            emitfile = True
            state = BFILE
            hunknum = 0
    if current_hunk:
        if current_hunk.complete():
            yield 'hunk', current_hunk
        else:
            raise PatchError(_("malformed patch %s %s") % (afile,
                             current_hunk.desc))

    if hunknum == 0 and dopatch and not gitworkdone:
        raise NoHunks

class UIDummy(object):
    verbose = False
    def note(self, s): pass

def applydiff_hacked(patch_str, targetfile, changed, strip=1, sourcefile=None, eol='\n'):
    """
    Reads a patch from fp and tries to apply it.

    The dict 'changed' is filled in with all of the filenames changed
    by the patch. Returns 0 for a clean patch, -1 if any rejects were
    found and 1 if there was any fuzz.

    If 'eol' is None, the patch content and patched file are read in
    binary mode. Otherwise, line endings are ignored when patching then
    normalized to 'eol' (usually '\n' or \r\n').
    """

    from StringIO import StringIO

    fp = StringIO(patch_str)
    ui = UIDummy()

    rejects = 0
    err = 0
    current_file = None
    gitpatches = None
    textmode = eol is not None

    def closefile():
        if not current_file:
            return 0
        current_file.close()
        return len(current_file.rej)

    one_file = False
    for state, values in iterhunks(ui, fp, sourcefile, textmode):
        if state == 'hunk':
            if not current_file:
                continue
            current_hunk = values
            ret = current_file.apply(current_hunk)
            if ret >= 0:
                changed.setdefault(current_file.fname, None)
                if ret > 0:
                    err = 1
        elif state == 'file':
            if one_file is not False:
                raise ValueError('Expected only one file!')
            else:
                one_file = True

            rejects += closefile()
            afile, bfile, first_hunk = values
            try:
                #current_file, missing = selectfile(afile, bfile, first_hunk,
                #                        strip)
                #current_file = patchfile(ui, current_file, opener, missing, eol)
                current_file = patchfile(ui, current_file, targetfile, False, eol)
            except PatchError, err:
                ui.warn(str(err) + '\n')
                current_file, current_hunk = None, None
                rejects += 1
                continue
        elif state == 'git':
            gitpatches = values
            cwd = os.getcwd()
            for gp in gitpatches:
                if gp.op in ('COPY', 'RENAME'):
                    copyfile(gp.oldpath, gp.path, cwd)
                changed[gp.path] = gp
        else:
            raise util.Abort(_('unsupported parser state: %s') % state)

    rejects += closefile()

    if rejects:
        return -1
    return err
