#!/usr/bin/python3

# Copyright 2017 Motylenok Mikhail
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

#	Paramters (TODO): 
#	--help		Display help screen
#	-q   		--quiet				Supress output
#	-a   		--rebuildall		Rebuild all targets
#	-i <FILE>   --input <FILE>		Specify config file
#   -y			--alwaysyes			Always answer "yes" 
#	-c <FORMAT> --sources <FORMAT>	Extension of source files (default: from config value)
#	-r <0 - 99>	--recmax <0 - 99>	Maximum deep of targets dependencies tree (default: 12)
#	-e <encode> --encoding <encode> Force strings encoding in this Python 3 format

# TODO: PEP8

#//example confiuration
#//"compiler" - use compiler (supported vars: "gcc", "g++", "clang")
#//"compiler_params" - paramters to compiler, for all microtargets
#//"linker_params" - paramters to linker for all project
#//"targets_build_path" - path to save .o files of compiled targets
#//"linker_output_file" - output file name and/or path
#//"postprocessing_shell" - shell commands to execute when fastbuild finished
#//"postprocessiong_if_failes" - exec shell commands if failed?
#//"untracked_action" - default action to do with untracked files (vard: "ask", "accept", "ignore")
#//"sources_endings" - what files to compile - most common: ".c", ".cpp"
#//"headers_endings" - all endings of headers files in projects: (example: ".h", ".hpp")
#//"macrotargets" - structure of pairs of macrotraget's name and array of 
#//			filename strings. Each string must contain one file name or one 
#//			correct regular expression for files. 


from subprocess import Popen, PIPE
from subprocess import call
import sys
import os
import json
import pprint 
import time
import hashlib

repositoryRoot = "."
relativeToRoot = "."

class bgcolors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def resolveFilesRegexp(macrotargetRegexp):
	child = Popen("dir -x1 " + macrotargetRegexp, shell=True, stdin=PIPE, stdout=PIPE) 
	files = list(child.stdout.read().split(b"\n"))

	if child.wait() != 0:
		sys.exit("\n\n" + macrotargetRegexp + " has incorrect, inaccessible or unreadable files. (status=" + str(child.wait())
			+ ") \"dir -x1 " + macrotargetRegexp + "\" shell command failed. Please check config and access rights.")

	return files


def resolveRelativePath(path):
	child = Popen("realpath --relative-to=\""+repositoryRoot+"\" " + path, shell=True, stdin=PIPE, stdout=PIPE) 
	files = list(child.stdout.read().split(b"\n"))

	if child.wait() != 0:
		sys.exit("\n\n" + path + " has incorrect, inaccessible or unreadable files. (status=" + str(child.wait())
			+ ") \"realpath --relative-to=. " + path + "\" shell command failed. Please check config and access rights.")

	return str(files[0].decode(sys.stdout.encoding))



def findDependeciesInFile(filename, deep, maxhops, deplist):
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
			#i = 0
			#print(" ", end="")
			#while i < deep:
			#	print("--", end="")	
			#	i = i + 1	
			#print(">  " + resolvedDependency) #!
			#
			#TODO: make visible

			deplist.append(resolvedDependency)
			
			ndp = deep + 1
			findDependeciesInFile(dependency, ndp, 24, deplist)		
	return deplist	



def getConfig():
	#TODO: read config file from filename in argv

	try:
		f = open("fastbuild.json", 'r')
		conftxt = f.read()
		f.close()		
	except IOError:
		sys.exit("fastbuild.json not found!")

	#print(conftxt)

	try:
		configObject = json.loads(conftxt)
	except json.decoder.JSONDecodeError:
		sys.exit("fastbuild.json incorrect!")

	#TODO: catch json expetions here
	#TODO: validate config

	return configObject


def checksumModificatedSinceLastFastbuild(fname, oldchk):
	#pprint.pprint(oldchk)
	if(fname not in oldchk.keys()):
		return True

	checksumNew = hashlib.md5(open(fname, 'rb').read()).hexdigest()
	checksumOld = oldchk[fname]
	if checksumNew == checksumOld:
		return False
	else:
		return True


def getModificatedByGit(correctEndings, untrackedAction, filestree, pollHeaders):
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
			candidateStr = str(candidate.decode(sys.stdout.encoding))
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
					#	continue

			if len(relativeToRoot) > 0:
				candidateName = relativeToRoot + "/" + candidateName

			if(not checksumModificatedSinceLastFastbuild(candidateName, oldchecksums)):
				continue

			print("Adding file: " + candidateName + " [" + end + "/" + start + "/git]")
			toprocessing.append(candidateName)
			#print(start + b"//////" + end)

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
										print("Adding file: " + header + " [" + end + "/md5]")
				else:
					if checksumModificatedSinceLastFastbuild(source, oldchecksums):
						if source not in toprocessing:
							for currentEnding in correctEndings:
								cnt = len(currentEnding)
								end = source[-1*cnt:]
								if end == currentEnding:
									toprocessing.append(source)
									print("Adding file: " + source + " [" + end + "/md5]")									

	return toprocessing



def selectDependecies(deps, headers):
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
						#print("comparing " + header + " and " + depheader + " (src = " + source + ") ")
						if(header == depheader):
							sourcesDependence.append(source)
							#print("--> Adding file: " + source + " [dependency of \""+header+"\"]")

	return sourcesDependence


def detectMissingObjFiles(filetree):
	if(not os.path.isdir("fastbuild")):
		print("fastbuild work directory not found -> rebuild all targets")
		os.makedirs("fastbuild")

	newObjFiles = list()

	for mt in filetree:
		for fn in filetree[mt]:
			objFilename = hashlib.md5(fn.encode('utf-8')).hexdigest()
			if(not os.path.exists("fastbuild/"+objFilename+".o")):
				#print("---> Adding file: " + fn + " [new object]")
				newObjFiles.append(fn)
			#print(mt + " -> " + fn + " -> " + )
	return newObjFiles


def generateChecksums(filetree):
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


def main():
	print("\n\nFastbuild - (c) 2017 by Motylenok \"muxamed666\" Mikhail")
	print(" * * * * Building project in FASTBUILD ALPHA MODE: \n")

	print("Step 0: Reading Config: ")
	cfg = getConfig()
	print("Done!")


	print("\nStep 1: Building and polling file list: ")

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
				item = str(files.decode(sys.stdout.encoding))
				if item != "":
					filescount = filescount + 1;
					src.append(item)
					#print("\t" + item)
					#TODO: make visible
		j = j + 1
		print("[" + str(int(round((j / targetscount) * 100 ))) + "%] In Progress...", end="\r")
		finalfiles.update({macrotarget: src})

	print("[100%] Done!              ")
	#print(finalfiles)


	print("\nStep 2: Resolving dependencies and building dependency tree: ")

	global repositoryRoot
	child = Popen("git rev-parse --show-toplevel", shell=True, stdin=PIPE, stdout=PIPE) 
	repositoryRoot = str(list(child.stdout.read().split(b"\n"))[0].decode(sys.stdout.encoding))

	finaldependency = dict()
	i = 0

	for mt in finalfiles:
		#print(bgcolors.HEADER + bgcolors.BOLD + "\n * * * * * * * * * " + mt + " * * * * * * * * * " + bgcolors.ENDC)
		#TODO: make visible
		srcdps = list()
		for fn in finalfiles.get(mt):
			i = i + 1
			#print(bgcolors.GREEN + bgcolors.BOLD + "\n>>>> " + fn + bgcolors.ENDC)
			#TODO: make visible
			deps = findDependeciesInFile(fn, 1, 24, list())
			filedeps = dict({fn : deps})
			srcdps.append(filedeps)
			print("[" + str(int(round( (i / filescount) * 100 ))) + "%] In Progress...", end="\r")
		finaldependency.update({mt : srcdps})

	print("[100%] Done!              ")
	#pprint.pprint(finaldependency, indent=4)


	print("\nStep 3: Calculating changes: ")

	global relativeToRoot
	child = Popen("realpath --relative-to=. " + repositoryRoot, shell=True, stdin=PIPE, stdout=PIPE) 
	relativeToRoot = str(list(child.stdout.read().split(b"\n"))[0].decode(sys.stdout.encoding))

	sources = getModificatedByGit(cfg["sources_endings"], cfg["untracked_action"], finaldependency, False)
	headers = getModificatedByGit(cfg["headers_endings"], cfg["untracked_action"], finaldependency, True)
	dependn = selectDependecies(finaldependency, headers)

	buildlist = sources

	for dep in dependn:
		if dep not in buildlist:
			buildlist.append(dep)
			print("Adding file: " + dep + " [dependency]")

	newobjs = detectMissingObjFiles(finalfiles)

	for obj in newobjs:
		if obj not in buildlist:
			buildlist.append(obj)
			print("Adding file: " + obj + " [new object]")

	if (len(buildlist) == 0):
		print("Already up-to-date or no changes deleted.")

	print("\nStep 4: Compiling microtargets: ")
	compiler = cfg["compiler"]
	cparams = cfg["compiler_params"]
	lparams = cfg["linker_params"]
	failmarker = False

	if (len(buildlist) == 0):
		print("Nothing to compile.")

	for target in buildlist:
		targetObjName = hashlib.md5(target.encode('utf-8')).hexdigest()
		targetObjPath = "fastbuild/" + targetObjName + ".o"
		compilerShell = compiler + " " + cparams + " " + lparams + " -c " + target +" -o " + targetObjPath
		#print(compilerShell)
		print("["+compiler+"] Compile " + target + " (object id: "+targetObjName+") ", end="")
		cstart = time.time()
		ret = call(compilerShell, shell=True)
		cend = time.time()
		if(ret != 0):
			failmarker = True
			print("[failed]")
		else:
			print("[Successful in " + str(round(cend - cstart, 2)) + " seconds]")

	if failmarker:
		print("Some targets failed to compile. Please fix errors, and run fastbuild again.")
		sys.exit(0)
	
	print("\nStep 5: Linking obj-files: ")
	outfile = cfg["linker_output_file"]

	print("["+compiler+"] Linking " + outfile + " ", end="")
	linkerShell = compiler + " fastbuild/*.o -o " + outfile + " " + lparams
	#print(linkerShell) 
	lstart = time.time()
	ret = call(linkerShell, shell=True)
	lend = time.time()
	if(ret != 0):
		failmarker = True
		print("[failed]")
	else:
		print("[Successful in " + str(round(lend - lstart, 2)) + " seconds]")

	#call("pwd", shell=True)

	if failmarker:
		print("Failed to link obj files. Please fix errors, and run fastbuild again.")
		sys.exit(0)

	if not failmarker: 
		generateChecksums(finaldependency)


if  __name__ ==  "__main__" :
	start = time.time() 
	main()
	end = time.time()
	print("\nFastbuild done in " + str(round(end - start, 2)) + " seconds. Thank you.")
