# Overview
Fastbuild is a simple experimental build-control software for C/C++ projects. 

This utility is designed to reduce the time and complexity of compiling code in C/C++ for projects that are already large enough to be compiled in a few minutes, but which have been written in such a way that the use of classic build automation tools is difficult

The primary objectives of this utility are:
* The possibility of faster compilation for medium-sized projects in C/C++
* Quick and painless integration into the work (just one small config file)
* Automatic detection of changes and their dependencies in the code (both using git and using their own hash tables)
* Caching changes ("the code written once is compiled once")
* Support for GCC, G++, and clang compilers. Requires a git version control in a project. 

# Installation
Installation is a simple procedure:
* clone this repository 
* run `sudo ./install.sh` (or switch to root and run `./install.sh`)
* if installation runs without errors, you can access it by `fastbuild` command

# Usage
Switch to your project's build directory and create there a configuration file. Most commonly it names "fastbuild.json". 
You can write it from strach, or just copy and modify the example file from this repo.

Availible config parameters:  

* "compiler" - use compiler (supported vars: "gcc", "g++", "clang")
* "compiler_params" - paramters to compiler, for all microtargets
* "linker_params" - paramters to linker for all project
* "targets_build_path" - path to save .o files of compiled targets
* "linker_output_file" - output file name and/or path
* "postprocessing_shell" - shell commands to execute when fastbuild finished
* "postprocessing_if_failed" - exec shell commands if failed?
* "untracked_action" - default action to do with untracked files (vars: "ask", "accept", "ignore")
* "sources_endings" - what files to compile (most common: ".c", ".cpp")
* "headers_endings" - all endings of headers files in projects: (example: ".h", ".hpp")
* "macrotargets" - structure of pairs of macrotraget's name and array of filename strings. Each string must contain one file name or one correct regular expression for files.

When you have this config file in your git repo, you can just type "fastbuild" and your project will be compiled.

Also, availible some command line parameters: 

* usage: fastbuild `[-h]` `[-q | -c]` `[-a]` `[-i INPUT]` `[-t]` `[-r RECMAX]` `[-e ENCODE]`

optional arguments:
*  `-h`, `--help`            show this help message and exit
*  `-q`, `--quiet`           Supress output
*  `-c`, `--compact`         Display not detailed output
*  `-a`, `--rebuildall`      Rebuild all targets
*  `-i INPUT`, `--input INPUT`  Specify config file (default: fastbuild.json)
*  `-t`, `--tree`            Display dependencies tree and exit
*  `-r RECMAX`, `--recmax RECMAX` Maximum deep of dependencies tree (default: 24)
*  `-e ENCODE`, `--encode ENCODE` Force strings encoding in this Python 3 format


# Legit?
It is free software, covered by Apache license. 
Firstly developed by muxamed666, basicly for Salo Intellect project. 
Without any warranty, but ideas and involvement are welcome.