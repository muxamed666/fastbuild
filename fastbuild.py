#!/usr/bin/python3

# Copyright 2017-2018 Motylenok Mikhail
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# FASTBUILD - for fast, custom, selective build of C/C++ software

# TODO: PEP8

#//example confiuration
#//"compiler" - use compiler (supported vars: "gcc", "g++", "clang")
#//"compiler_params" - paramters to compiler, for all microtargets
#//"linker_params" - paramters to linker for all project
#//"targets_build_path" - path to save .o files of compiled targets
#//"linker_output_file" - output file name and/or path
#//"postprocessing_shell" - shell commands to execute when fastbuild finished
#//"postprocessing_if_failed" - exec shell commands if failed?
#//"untracked_action" - default action to do with untracked files (vars: "ask", "accept", "ignore")
#//"sources_endings" - what files to compile (most common: ".c", ".cpp")
#//"headers_endings" - all endings of headers files in projects: (example: ".h", ".hpp")
#//"macrotargets" - structure of pairs of macrotraget's name and array of 
#//         filename strings. Each string must contain one file name or one 
#//         correct regular expression for files. 


from subprocess import Popen, PIPE
from subprocess import call
import fnmatch
import argparse
import sys
import os
import json
import pprint 
import time
import hashlib
import threading
import copy

repositoryRoot = "."
relativeToRoot = "."
outputlevel = 0
rebuildall = False
configFileName = "fastbuild.json"
treeOut = False
recursionThreshold = 24
systemEncoding = sys.stdout.encoding
usedFasttreeFilenames = list()
failmarker = False
threadLimit = 1


class bgcolors:
    """Class contains background color escapes for terminal """
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class pregenerationError(Exception):
    """Exception class used for json and files error in pregenerated dependency trees """
    def __init__(self, message):
        self.message = message

def fastprint(txt, level=0, fastend=None):
    """Function implements output operation.
    Level paramter allows to cut or verbose output strings.
    level 0 is global (all strings), 1 - important strings, 2 - error strings
    """
    if (level < outputlevel):
        return 

    if(fastend == None):
        print(txt)
    else:
        print(txt, end=fastend)


def resolveFilesRegexp(macrotargetRegexp):
    """Resolve regular expressions in file names. For example,
    it will convert somedir/*.cpp to somedir/foo.cpp and somedir/bar.cpp 
    (if those file both are on disk in somedir)
    calls to dir utillity
    """
    child = Popen("dir -x1 " + macrotargetRegexp, shell=True, stdin=PIPE, stdout=PIPE) 
    files = list(child.stdout.read().split(b"\n"))

    if child.wait() != 0:
        sys.exit("\n\n" + macrotargetRegexp + " has incorrect, inaccessible or unreadable files. (status=" + str(child.wait())
            + ") \"dir -x1 " + macrotargetRegexp + "\" shell command failed. Please check config and access rights.")

    return files


def resolveRelativePath(path):
    """Converts relative paths to absolute paths using the realpath utility
    This function is called for each dependency file in C/C++ code, so 
    all filenames are comparable to each other.
    """
    child = Popen("realpath --relative-to=\""+repositoryRoot+"\" " + path, shell=True, stdin=PIPE, stdout=PIPE) 
    files = list(child.stdout.read().split(b"\n"))

    if child.wait() != 0:
        sys.exit("\n\n" + path + " has incorrect, inaccessible or unreadable files. (status=" + str(child.wait())
            + ") \"realpath --relative-to=. " + path + "\" shell command failed. Please check config and access rights.")

    return str(files[0].decode(systemEncoding))



def findDependeciesInFile(filename, deep, maxhops, deplist):
    """The function recursively searches for directives for inclusions in C++ code files, 
    specifies the maximum depth of recursion. Files are included in the returned list 
    of dependencies without duplicates.
    """
    if deep >= maxhops:
        return deplist

    try:
        f = open(filename, 'r')
        filetxt = f.read()
        f.close()       
    except IOError:
        sys.exit(filename + " file read error! Critical!")

    offset = 0

    while (1):
        includeStart = filetxt.find("#include \"", offset)

        if includeStart == -1:
            break

        if filetxt[includeStart - 2 : includeStart] == "//":
            offset = offset + 12
            continue

        includeEnd = filetxt.find("\"", includeStart + 11, includeStart + 128)
        dependency = filetxt[includeStart+10 : includeEnd]
        
        offset = includeStart + 15

        slash = filename.rfind("/")
        path = ""

        if slash != -1:
            path = filename[0 : slash]

        if path != "":
            dependency = path + "/" + dependency 

        resolvedDependency = resolveRelativePath(dependency)

        if not (resolvedDependency in deplist):
            if treeOut:
                i = 0
                fastprint(" ", fastend="")
                while i < deep:
                    fastprint("--", fastend="") 
                    i = i + 1   
                fastprint(">  " + resolvedDependency) #!
                
            deplist.append(resolvedDependency)
            
            ndp = deep + 1
            findDependeciesInFile(dependency, ndp, recursionThreshold, deplist)     
    
    #dump tree only for 1-st range files
    if deep == 1:
        pregenerationDumpFilename = "fastbuild/" + hashlib.md5(open(filename, 'rb').read()).hexdigest() + ".fasttree"
        usedFasttreeFilenames.append(pregenerationDumpFilename)
        pdfile = open(pregenerationDumpFilename, "w")
        pdfile.write(json.dumps(deplist))
        pdfile.close()

    return deplist  


def getConfig():
    """Reads the configuration file and converts it from the json format to a 
    dictionary that stores the build parameters of the current project. Recommendations for 
    filling the configuration file can be found in the Readme or you can study the sample file
    """
    try:
        f = open(configFileName, 'r')
        conftxt = f.read()
        f.close()       
    except IOError:
        sys.exit("Error while open file " + configFileName + "!")

    #print(conftxt)

    try:
        configObject = json.loads(conftxt)
    except json.decoder.JSONDecodeError:
        sys.exit("config file is incorrect!")

    #TODO: catch json expetions here
    #TODO: validate config

    return configObject


def checksumModificatedSinceLastFastbuild(fname, oldchk):
    """Determines whether the checksum of the file has changed since the 
    last time the hash table was saved to the disk.
    """
    #pprint.pprint(oldchk)
    if(fname not in oldchk.keys()):
        return True

    if rebuildall:
        return True

    checksumNew = hashlib.md5(open(fname, 'rb').read()).hexdigest()
    checksumOld = oldchk[fname]
    if checksumNew == checksumOld:
        return False
    else:
        return True


def getModificatedByGit(correctEndings, untrackedAction, filestree, pollHeaders):
    """With the repository data, git determines the modification of 
    files in the file tree with the specified extensions. For files that are not 
    specified in git, the modified function attempts to determine the fact of the 
    change using a hash table.
    """
    gitfiles = list(Popen("git status --porcelain", shell=True, stdin=PIPE, stdout=PIPE).stdout.read().split(b"\n"))
    try:
        oldchecksums = json.loads(open("fastbuild/repository.md5", 'r').read())
    except IOError:
        oldchecksums = dict()

    toprocessing = list()

    #M -> modifing -> rebuild
    #A -> new file -> rebuild
    #D -> deleted -> ignore
    #R -> renamed -> rebuild
    #C -> copied -> rebuild
    #?? -> untracked -> ask user

    for candidate in gitfiles:
        for currentEnding in correctEndings:
            cnt = len(currentEnding)
            candidateStr = str(candidate.decode(systemEncoding))
            start = candidateStr[1:2]
            end = candidateStr[-1*cnt:]
            candidateName = candidateStr[3:]

            if (end != currentEnding):
                continue

            if (start == "D"):
                continue

            if (start == "?"):
                if untrackedAction == "ignore":
                    continue
                #elif untrackedAction == "ask":
                    #print("file \"" + candidateStr + "\"have untracked git status, it is not in git repository. \n\
                    #If this is just a new file(s) in your project, please make \"git add [filename]\" to add them in your\n\
                    #project repository as soon as possible.\n\
                    #Also, you can set default action for untracked files by untrackedAction parameter in config (ask, accept or ignore)\n\
                    #\n")
                    #quest = "Add this file to build list?"
                    #cho = query_yes_no(quest, default="no")
                    #if not cho:
                    #   continue

            if len(relativeToRoot) > 0:
                candidateName = relativeToRoot + "/" + candidateName

            if(not checksumModificatedSinceLastFastbuild(candidateName, oldchecksums)):
                continue

            fastprint("Adding file: " + candidateName + " [" + end + "/" + start + "/git]")
            toprocessing.append(candidateName)
            #print(start + b"//////" + end)

    # Search in hashes

    for mt in filestree:
        for files in filestree[mt]:
            for source in files:
                if pollHeaders:
                    for headers in files[source]:
                        if (len(relativeToRoot) > 0):
                            header = relativeToRoot + "/" + headers
                        else:
                            header = headers
                        if checksumModificatedSinceLastFastbuild(header, oldchecksums):
                            if header not in toprocessing:
                                for currentEnding in correctEndings:
                                    cnt = len(currentEnding)
                                    end = header[-1*cnt:]
                                    if end == currentEnding:
                                        toprocessing.append(header)
                                        if not rebuildall:
                                            fastprint("Adding file: " + header + " [" + end + "/md5]")
                                        else:
                                            fastprint("Adding file: " + header + " [" + end + "/rebuildall]")
                else:
                    if checksumModificatedSinceLastFastbuild(source, oldchecksums):
                        if source not in toprocessing:
                            for currentEnding in correctEndings:
                                cnt = len(currentEnding)
                                end = source[-1*cnt:]
                                if end == currentEnding:
                                    toprocessing.append(source)
                                    if not rebuildall:
                                        fastprint("Adding file: " + source + " [" + end + "/md5]")
                                    else:
                                        fastprint("Adding file: " + source + " [" + end + "/rebuildall]")                                   

    return toprocessing



def selectDependecies(deps, headers):
    """Finds which source files depend on the changed header files. 
    Forms and returns a list of these dependencies.
    """
    sourcesDependence = list()

    for macrotarget in deps:
        for sourcelst in deps[macrotarget]:
            for source in sourcelst:
                for sourcedeps in sourcelst[source]:
                    for header in headers:
                        if (len(relativeToRoot) > 0):
                            depheader = relativeToRoot + "/" + sourcedeps
                        else:
                            depheader = sourcedeps
                        #fastprint("comparing " + header + " and " + depheader + " (src = " + source + ") ")
                        if(header == depheader):
                            sourcesDependence.append(source)
                            #fastprint("--> Adding file: " + source + " [dependency of \""+header+"\"]")

    return sourcesDependence


def detectMissingObjFiles(filetree):
    """Finds which object files are not in the cache to 
    add them to the list for recompilation.
    """
    
    if(not os.path.isdir("fastbuild")):
        fastprint("fastbuild work directory not found -> rebuild all targets", level=1)
        os.makedirs("fastbuild")

    newObjFiles = list()

    for mt in filetree:
        for fn in filetree[mt]:
            objFilename = hashlib.md5(fn.encode('utf-8')).hexdigest()
            if(not os.path.exists("fastbuild/"+objFilename+".o")):
                #fastprint("---> Adding file: " + fn + " [new object]")
                newObjFiles.append(fn)
            #print(mt + " -> " + fn + " -> " + )
    return newObjFiles


def generateChecksums(filetree):
    """Generates a hash table with checksums for the project files so that 
    the program can then find changes to the next build from the current one.
    """

    sums = dict()

    for macrotarget in filetree:
        for sourcelst in filetree[macrotarget]:
            for source in sourcelst:
                if source not in sums.keys():
                    checksum = hashlib.md5(open(source, 'rb').read()).hexdigest()
                    sums.update({source : checksum})
                for sourcedeps in sourcelst[source]:
                    if (len(relativeToRoot) > 0):
                        depheader = relativeToRoot + "/" + sourcedeps
                    else:
                        depheader = sourcedeps
                    
                    if depheader not in sums.keys():
                        checksum = hashlib.md5(open(depheader, 'rb').read()).hexdigest()
                        sums.update({depheader : checksum})

    wt = open("fastbuild/repository.md5", "w")
    wt.write(json.dumps(sums))
    wt.close()

    #pprint.pprint(sums)


def fileHasPregeneratedTree(filepath):
    """Checks if file has a pregenerated dependency tree
    If checksum of file is changed, dependecy tree is outdated and rebuild is needed
    """
    try:
        checksumNew = hashlib.md5(open(filepath, 'rb').read()).hexdigest()
        filename = "fastbuild/" + checksumNew + ".fasttree"
        readableTreeFile = open(filename)
    except IOError:
        return False
    return True


def restorePregeneratedDependenciesForFile(filepath):
    """Reads pregenerated dependency tree for specified file"""
    try:
        checksumNew = hashlib.md5(open(filepath, 'rb').read()).hexdigest()
        filename = "fastbuild/" + checksumNew + ".fasttree"
        usedFasttreeFilenames.append(filename)
        readableTreeFile = open(filename)
        deptxt = readableTreeFile.read()
    except IOError:
        fastprint("Error reading file " + filename + "!")
        raise pregenerationError("File Error")
    
    try:
        depobject = json.loads(deptxt)
    except json.decoder.JSONDecodeError:
        fastprint("json structure in file "+filename+" is incorrect!")    
        raise pregenerationError("JSON Error")

    return depobject


def microtargetBuilder(localBuildlist, localCompiler, localCParams, localLParams, threadNumber):
    """Builds specified range of microtargets in separate thread"""
    for target in localBuildlist:
        targetObjName = hashlib.md5(target.encode('utf-8')).hexdigest()
        targetObjPath = "fastbuild/" + targetObjName + ".o"
        compilerShell = localCompiler + " " + localCParams + " " + localLParams + " -c " + target +" -o " + targetObjPath
        #fastprint(compilerShell)
                
        cstart = time.time()
        ret = call(compilerShell, shell=True)
        cend = time.time()
        
        if(ret != 0):
            global failmarker
            failmarker = True
            fastprint("["+localCompiler+"] Compile " + target + " (object id: "+targetObjName+") " 
                + "[failed] in thread #" + str(threadNumber))
        else:
            fastprint("["+localCompiler+"] Compile " + target + " (object id: "+targetObjName+") " 
                + "[Successful in " + str(round(cend - cstart, 2)) + " seconds] in thread #" + str(threadNumber))


def separateBuildLists(globalBuildlist, threads):
    """Separates build list per different threads"""
    listSize = int(len(globalBuildlist) / threads)
    listOfLists = list()
    tmpList = list()
    itr = 0

    if listSize == 0:
        listOfLists.append(copy.deepcopy(globalBuildlist))
        return listOfLists

    #fastprint(str(len(globalBuildlist)) + " - all")
    #fastprint(str(listSize) + " - one thread")

    for oneTarget in globalBuildlist:
        tmpList.append(oneTarget)
        itr = itr + 1
        if ((itr == listSize) and (len(listOfLists) < threads)):
            copylist = list()
            copylist = copy.deepcopy(tmpList)
            listOfLists.append(copylist)
            tmpList.clear()
            itr = 0

    listOfLists[0].extend(tmpList)

    #pprint.pprint(listOfLists, indent=4)
    return listOfLists


def main():
    """ main() function, consistently performs all the steps of the project's build porcess """
    fastprint(bgcolors.BOLD + bgcolors.UNDERLINE + "\nFastbuild - (c) by Motylenok \"muxamed666\" Mikhail\n" + bgcolors.ENDC)

    fastprint("Step 0: Reading Config: ", level=1)
    cfg = getConfig()
    fastprint("Done!", level=1)


    fastprint("\nStep 1: Building and polling file list: ", level=1)

    finalfiles = dict()
    filescount = 0
    targetscount = len(cfg["macrotargets"])
    j = 0

    for macrotarget in cfg["macrotargets"]:
        #print("\nFiles for macrotarget \"" + macrotarget + "\": ")
        #TODO: make visible
        src = list()
        for filelist in cfg["macrotargets"][macrotarget]:
            for files in resolveFilesRegexp(filelist):
                item = str(files.decode(systemEncoding))
                if item != "":
                    filescount = filescount + 1;
                    src.append(item)
                    #print("\t" + item)
                    #TODO: make visible
        j = j + 1
        fastprint("[" + str(int(round((j / targetscount) * 100 ))) + "%] In Progress...", fastend="\r", level=1)
        finalfiles.update({macrotarget: src})

    fastprint("[100%] Done!              ", level=1)
    #fastprint(finalfiles)


    fastprint("\nStep 2: Resolving dependencies and building dependency tree: ", level=1)

    global usedFasttreeFilenames
    global repositoryRoot
    child = Popen("git rev-parse --show-toplevel", shell=True, stdin=PIPE, stdout=PIPE) 
    repositoryRoot = str(list(child.stdout.read().split(b"\n"))[0].decode(systemEncoding))

    finaldependency = dict()
    i = 0
    restoredNodesCount = 0
    outdatedNodesCount = 0

    for mt in finalfiles:
        if treeOut:
            fastprint(bgcolors.HEADER + bgcolors.BOLD + "\n " + mt + " * * * : " + bgcolors.ENDC)
        srcdps = list()
        for fn in finalfiles.get(mt):
            i = i + 1
            if treeOut:
                fastprint(bgcolors.GREEN + bgcolors.BOLD + "\n>>>> " + fn + bgcolors.ENDC)
            if ((not fileHasPregeneratedTree(fn)) or treeOut):
                outdatedNodesCount = outdatedNodesCount + 1
                if treeOut:
                    fastprint("Tree node is out of date, rebuilding...")
                deps = findDependeciesInFile(fn, 1, recursionThreshold, list())
            else:
                restoredNodesCount = restoredNodesCount + 1
                if treeOut:
                    fastprint("Tree generation not performed here, tree restored from cache...")
                try:
                    deps = restorePregeneratedDependenciesForFile(fn)
                except pregenerationError:
                    deps = findDependeciesInFile(fn, 1, recursionThreshold, list())
            filedeps = dict({fn : deps})
            srcdps.append(filedeps)
            if not treeOut:
                fastprint("[" + str(int(round( (i / filescount) * 100 ))) + "%] In Progress...", fastend="\r", level=1)
        finaldependency.update({mt : srcdps})

    fastprint("[100%] Done!              ", level=1)
    #pprint.pprint(finaldependency, indent=4)

    #cleanup
    deletedFiles = 0
    listOfFiles = os.listdir('fastbuild/')  
    clPattern = "*.fasttree"  
    for clEntry in listOfFiles:  
        if fnmatch.fnmatch(clEntry, clPattern):
            clFilename = "fastbuild/"+clEntry
            if clFilename not in usedFasttreeFilenames:
                    os.remove(clFilename)
                    deletedFiles = deletedFiles + 1

    if treeOut:
        sys.exit(0)

    fastprint("\nDependency tree: "+str(filescount)+" nodes total, "+str(restoredNodesCount)
        +" nodes restored, "+str(outdatedNodesCount)+" nodes out of date.")
    fastprint("Dependency tree: "+str(len(usedFasttreeFilenames))+" nodes in use, "
        +str(deletedFiles)+" nodes cleaned up.")



    fastprint("\nStep 3: Calculating changes: ", level=1)

    global relativeToRoot
    child = Popen("realpath --relative-to=. " + repositoryRoot, shell=True, stdin=PIPE, stdout=PIPE) 
    relativeToRoot = str(list(child.stdout.read().split(b"\n"))[0].decode(systemEncoding))

    sources = getModificatedByGit(cfg["sources_endings"], cfg["untracked_action"], finaldependency, False)
    headers = getModificatedByGit(cfg["headers_endings"], cfg["untracked_action"], finaldependency, True)
    dependn = selectDependecies(finaldependency, headers)

    buildlist = sources

    for dep in dependn:
        if dep not in buildlist:
            buildlist.append(dep)
            fastprint("Adding file: " + dep + " [dependency]")

    newobjs = detectMissingObjFiles(finalfiles)

    for obj in newobjs:
        if obj not in buildlist:
            buildlist.append(obj)
            fastprint("Adding file: " + obj + " [new object]")

    if (len(buildlist) == 0):
        fastprint("Already up-to-date or no changes detected.", level=1)
    else:
        fastprint("Done!", level=1)


    fastprint("\nStep 4: Compiling microtargets: ", level=1)
    compiler = cfg["compiler"]
    cparams = cfg["compiler_params"]
    lparams = cfg["linker_params"]

    if (len(buildlist) == 0):
        fastprint("Nothing to compile.", level=1)

    global failmarker

    threadList = list()

    #multithreading compilation
    if(threadLimit == 1):
        microtargetBuilder(buildlist, compiler, cparams, lparams, 0)
    else:
        if(len(buildlist) > 0):
            fastprint("Compiling microtargets in up to " + str(threadLimit) + " threads")
            buildLists = separateBuildLists(buildlist, threadLimit)
            thr = 0
            for oneBuildList in buildLists:
                t = threading.Thread(target=microtargetBuilder, args=(oneBuildList, compiler, cparams, lparams, thr))
                t.start()
                threadList.append(t)
                thr = thr + 1
            for oneThread in threadList:
                oneThread.join()
             


    if failmarker:
        fastprint("Some targets failed to compile. Please fix errors, and run fastbuild again.", level=2)
        sys.exit(0)
    
    #linking

    fastprint("\nStep 5: Linking obj-files: ", level=1)
    outfile = cfg["linker_output_file"]

    fastprint("["+compiler+"] Linking " + outfile + " ", fastend="")
    linkerShell = compiler + " fastbuild/*.o -o " + outfile + " " + lparams
    #fastprint(linkerShell) 
    lstart = time.time()
    ret = call(linkerShell, shell=True)
    lend = time.time()
    if(ret != 0):
        failmarker = True
        fastprint("[failed]")
    else:
        fastprint("[Successful in " + str(round(lend - lstart, 2)) + " seconds]")
        fastprint("Done!", level=1)

    #call("pwd", shell=True)

    if failmarker:
        fastprint("Failed to link obj files. Please fix errors, and run fastbuild again.", level=2)
        sys.exit(0)

    if not failmarker: 
        generateChecksums(finaldependency)


    fastprint("\nStep 6: Running postprocessing shell: ", level=1)  

    if ("postprocessing_shell" in cfg.keys()) and (cfg["postprocessing_shell"] != ""):
        if not failmarker:
            call(cfg["postprocessing_shell"], shell=True)
        else:
            if cfg["postprocessing_if_failed"]:
                call(cfg["postprocessing_shell"], shell=True)
            else:
                fastprint("Postprocessing disabled on fails by config parameter", level=1)
    else:
        fastprint("Postprocessing disabled", level=1)


if  __name__ ==  "__main__" :
    #passing args and start main()
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-q", "--quiet", help="Supress output", action="store_true")
    group.add_argument("-c", "--compact", help="Display not detailed output", action="store_true")
    parser.add_argument("-a", "--rebuildall", help="Rebuild all targets", action="store_true")
    parser.add_argument("-i", "--input", help="Specify config file (default: fastbuild.json)", type=str)
    parser.add_argument("-t", "--tree", help="Display dependencies tree and exit", action="store_true")
    parser.add_argument("-r", "--recmax", help="Maximum deep of dependencies tree (default: 24)", type=int)
    parser.add_argument("-e", "--encode", help="Force strings encoding in this Python 3 format")
    parser.add_argument("-p", "--threads", help="Number of threads (min 1, max 32, default 1)", type=int)
    args = parser.parse_args()
    
    if args.quiet:
        outputlevel = 2

    if args.compact:
        outputlevel = 1

    if args.rebuildall:
        rebuildall = True

    if args.input:
        configFileName = args.input

    if args.tree:
        treeOut = True

    if args.recmax:
        if (args.recmax < 0 or args.recmax > 99):
            sys.exit("Recmax must be in range from 0 to 99! (default: 24)")
        else:
            recursionThreshold = args.recmax

    if args.threads:
        if (args.threads < 1 or args.threads > 32):
            sys.exit("Thread number must be in range from 1 to 32! (default: 1)")
        else:
            threadLimit = args.threads

    if args.encode:
        systemEncoding = args.encode


    start = time.time() 
    main()
    end = time.time()
    fastprint(bgcolors.BOLD + "\nFastbuild done in " + str(round(end - start, 2)) + " seconds. Thank you." + bgcolors.ENDC, level=1)
