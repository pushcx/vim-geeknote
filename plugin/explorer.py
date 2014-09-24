import vim
import re

from utils import *
from geeknote.geeknote import *

#======================== Classes ============================================#

class Node(object):
    guid = None
    row  = -1

class NotebookNode(Node):
    def __init__(self, notebook):
        self.notebook = notebook
        self.notes    = []
        self.setName(notebook.name)

    def setName(self, name):
        self.name = name

class NoteNode(Node):
    def __init__(self, note, notebook):
        self.note     = note
        self.notebook = notebook
        self.setTitle(note.title)

    def setTitle(self, title):
        self.title = title

class Explorer(object):

    # A list of nodes for each notebook displayed in the explorer.
    notebooks = []

    # Maps the guid of each node to its underlying node object (includes notes)
    guidMap = {}

    # Maps notebook guids to the notebook's expand state (expanded/!explanded)
    expandState = {}

    #
    # A list of nodes (notebooks or nodes) that have been modified since the
    # last time the navigation window was synchronized with the server.
    #
    modifiedNodes = []

    # The file used to back the data store in the navigation window.
    dataFile = None

    def __init__(self, geeknote, dataFile, buf):
        self.geeknote  = geeknote
        self.noteStore = self.geeknote.getNoteStore()
        self.authToken = self.geeknote.authToken

        self.dataFile = dataFile
        self.buf      = buf

        try:
            self.refresh()
        except:
            vim.command('echoerr "Failed to retrieve data from server"')
            raise

        self.initView()
        self.render()

        # XXX: Move this into vim_geeknote.py
        autocmd('BufWritePre', self.dataFile.name, ':call Vim_GeeknoteSync()')

    def __del__(self):
        try:
            self.dataFile.close()
        except:
            pass

    def applyChanges(self):
        if isBufferModified(self.buf.number) is False:
            return

        for row in xrange(len(self.buf)):
            line = self.buf[row]

            # Look for changes to notes.
            r = re.compile('^\s+(.+)\[(.+)\]$')
            m = r.match(line)
            if m: 
                title = m.group(1).strip()
                guid  = m.group(2)
                node  = self.guidMap[guid]
                if isinstance(node, NoteNode):
                    # Did the user change the note's title?
                    if title != node.title:
                        node.setTitle(title)
                        if node not in self.modifiedNodes:
                            self.modifiedNodes.append(node)

                    # Did the user move the note into a different notebook?
                    navNotebook = self.findNotebookForNode(row)
                    if navNotebook is not None:
                        if navNotebook.guid != node.notebook.guid:
                            node.notebook = navNotebook
                            if node not in self.modifiedNodes:
                                self.modifiedNodes.append(node)
                continue

            # Look for changes to notebooks.
            r = re.compile('^[\+-](.+)\[(.+)\]$')
            m = r.match(line)
            if m:
                name = m.group(1).strip()
                guid = m.group(2)
                node = self.guidMap[guid]
                if isinstance(node, NotebookNode):
                    if name != node.name:
                        node.setName(name)
                        self.modifiedNodes.append(node)
                continue

    def addNotebook(self, notebook):
        node = NotebookNode(notebook)
        self.notebooks.append(node)
        self.notebooks.sort(key=lambda n: n.notebook.name.lower())

        self.guidMap[notebook.guid] = node

        notes = self.getNotes(notebook)
        notes.sort(key=lambda n: n.title)
        for note in notes:
            self.addNote(note, notebook)

        if notebook.guid not in self.expandState:
            self.expandState[notebook.guid] = False

    def addNote(self, note, notebook):
        node = NoteNode(note, notebook)
        notebookNode = self.guidMap[notebook.guid]
        notebookNode.notes.append(node)

        self.guidMap[note.guid] = node

    def closeAll(self):
        for guid in self.expandState:
            self.expandState[guid] = False

    def expandAll(self):
        for guid in self.expandState:
            self.expandNotebook(guid)

    def expandNotebook(self, guid):
        self.expandState[guid] = True

    #
    # Search upwards, starting at the given row number and return the first
    # note node found. 
    #
    def findNotebookForNode(self, nodeRow):
        while nodeRow > 0:
            guid = self.getNodeGuid(self.buf[nodeRow])
            if guid is not None: 
                node = self.guidMap[guid]
                if isinstance(node, NotebookNode):
                    return node.notebook
            nodeRow -= 1
        return None

    def getBuffer(self):
        return self.buf

    def getNotebook(self, guid):
        node = self.guidMap[guid]
        if isinstance(node, NotebookNode):
            return node.notebook
        return None

    def getNote(self, guid):
        node = self.guidMap[guid]
        if isinstance(node, NoteNode):
            return node.note
        return None

    #
    # Return a list of all notes contained in the given notebook.
    #
    def getNotes(self, notebook):
        request = 'notebook:"%s" ' % notebook.name
        count   = 20

        result = self.geeknote.findNotes(request, count, False)
        update_count = lambda c: max(c - len(result.notes), 0)
        count = update_count(count)
        
        while ((result.totalNotes != len(result.notes)) and count != 0):
            offset = len(result.notes)
            result.notes += self.geeknote.findNotes(request, count,
                    False, offset).notes
            count = update_count(count)

        notes = []
        for key, note in enumerate(result.notes):
            notes.append(note)
        return notes

    def getContainingNotebook(self, guid):
        node = self.guidMap[guid]
        if isinstance(node, NoteNode):
            return node.notebook
        return None

    def getSelectedNotebook(self):
        prevWin = getActiveWindow()
        setActiveBuffer(self.buf)
        text = vim.current.line
        setActiveWindow(prevWin)

        guid = self.getNodeGuid(text)
        if guid is not None:
            node = self.guidMap[guid]
            if isinstance(node, NotebookNode):
                return node.notebook
            if isinstance(node, NoteNode):
                return node.notebook
        return None

    def getNodeGuid(self, nodeText):
        r = re.compile('^.+\[(.+)\]$')
        m = r.match(nodeText)
        if m: 
            return m.group(1)
        return None

    def initView(self):
        origWin = getActiveWindow()
        setActiveBuffer(self.buf)

        wnum = getActiveWindow()
        bnum = self.buf.number

        setWindowVariable(wnum, 'winfixwidth', True)
        setWindowVariable(wnum, 'wrap'       , False)
        setWindowVariable(wnum, 'cursorline' , True)
        setBufferVariable(bnum, 'swapfile'   , False)
        setBufferVariable(bnum, 'buftype'    , 'quickfix')
        setBufferVariable(bnum, 'bufhidden'  , 'hide')

        vim.command('setfiletype geeknote')
        setActiveWindow(origWin)

    #
    # Move the given note into the specified notebook.
    #
    def moveNote(self, note, notebook):
        note.notebookGuid = notebook.guid
        try:
            return self.noteStore.updateNote(self.authToken, note)
        except:
            vim.command('echoerr "Failed to move note."')
        return None

    def refresh(self):
        del self.notebooks[:]
        self.guidMap.clear()

        notebooks = GeekNote().findNotebooks()
        for notebook in notebooks:
            self.addNotebook(notebook)

    def renameNotebook(self, notebook, name):
        notebook.name = name
        try:
            return self.noteStore.updateNotebook(self.authToken, notebook)

        except Errors.EDAMUserException as e:
            vim.command('echoerr "%s"' % e.string)

        except Errors.EDAMSystemException as e:
            vim.command('echoerr "Error %d: %s"' % \
                (e.errorCode, e.string))

        except Errors.EDAMNotFoundException as e:
            vim.command('echoerr "Error: not found %s (type=%s)"' % \
                (e.key, e.identifier))

        return None

    def renameNote(self, note, title):
        note.title = title
        try:
            return self.noteStore.updateNote(self.authToken, note)

        except Errors.EDAMUserException as e:
            vim.command('echoerr "%s"' % e.string)

        except Errors.EDAMSystemException as e:
            vim.command('echoerr "Error %d: %s"' % \
                (e.errorCode, e.string))

        except Errors.EDAMNotFoundException as e:
            vim.command('echoerr "Error: not found %s (type=%s)"' % \
                (e.key, e.identifier))

        return None

    def selectNode(self, guid):
        origWin = getActiveWindow()
        setActiveBuffer(self.buf)
        node = self.guidMap[guid]
        if node is not None:
            vim.current.window.cursor = (node.row, 0)
        setActiveWindow(origWin)

    def selectNotebook(self, notebook):
        self.selectNode(notebook.guid)

    def selectNotebookIndex(self, index):
        if index < len(self.notebooks):
            node = self.notebooks[index]
            self.selectNode(node.notebook.guid)

    def selectNote(self, note):
        self.selectNode(note.guid)

    def toggleNotebook(self, guid):
        node = self.guidMap[guid]
        if isinstance(node, NotebookNode):
            self.expandState[guid] = not self.expandState[guid]

    # Render the navigation buffer in the navigation window..
    def render(self):
        origWin = getActiveWindow()
        setActiveBuffer(self.buf)

        # 
        # Before overwriting the naviagation window, look for any changes made
        # by the user. Do not synchronize them yet with the server, just make
        # sure they are not lost.
        #
        self.applyChanges()

        # Clear the navigation buffer to get rid of old content (if any).
        del self.buf[:]

        # Prepare the new content and append it to the navigation buffer.
        content = []
        content.append('Notebooks:')
        content.append('{:=^90}'.format('='))

        row = 3
        for node in self.notebooks:
            notebook = node.notebook
            numNotes = len(node.notes)
            expand   = self.expandState[notebook.guid]

            line  = '-' if expand is True or numNotes == 0 else '+'
            line += ' ' + node.name
            content.append('{:<50} [{}]'.format(line, notebook.guid))
            node.row = row
            row += 1

            if expand is True:
                for noteNode in node.notes:
                    note  = noteNode.note
                    title = noteNode.title

                    line  = '    {:<46} [{}]'.format(title, note.guid)
                    content.append(line)
                    noteNode.row = row
                    row += 1
        self.buf.append(content, 0)

        #
        # Write the navigation window but disable BufWritePre events before
        # doing so. We only want to check for user changes when the user was
        # the one that saved the buffer.
        #
        ei = vim.eval('&ei')
        vim.command('set ei=BufWritePre')
        vim.command("write!")
        vim.command('set ei={}'.format(ei))

        setActiveWindow(origWin)

    def syncChanges(self):
        self.applyChanges()
        for node in self.modifiedNodes:
             if isinstance(node, NotebookNode):
                 self.renameNotebook(node.notebook, node.name)
                 continue
             if isinstance(node, NoteNode):
                 if node.title != node.note.title:
                     self.renameNote(node.note, node.title)
                 if node.notebook.guid != node.note.notebookGuid:
                     self.moveNote(node.note, node.notebook)
                 continue
        del self.modifiedNodes[:]

