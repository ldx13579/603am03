@echo off
REM Build script for Smart Parking Garage System
REM Requires gcc (MinGW) in PATH

if not exist obj mkdir obj
if not exist bin mkdir bin

set CFLAGS=-std=c11 -Wall -Wextra -I./include -DUSE_THREADING

echo Compiling...
gcc %CFLAGS% -c src/main.c -o obj/main.o
gcc %CFLAGS% -c src/garage.c -o obj/garage.o
gcc %CFLAGS% -c src/state_machine.c -o obj/state_machine.o
gcc %CFLAGS% -c src/path_planner.c -o obj/path_planner.o
gcc %CFLAGS% -c src/billing.c -o obj/billing.o
gcc %CFLAGS% -c src/logger.c -o obj/logger.o
gcc %CFLAGS% -c src/cli.c -o obj/cli.o
gcc %CFLAGS% -c src/sync.c -o obj/sync.o
gcc %CFLAGS% -c src/statistics.c -o obj/statistics.o
gcc %CFLAGS% -c src/fault.c -o obj/fault.o
gcc %CFLAGS% -c src/scheduler.c -o obj/scheduler.o
gcc %CFLAGS% -c src/simulation.c -o obj/simulation.o

echo Linking...
gcc -o bin/parking_garage.exe obj/main.o obj/garage.o obj/state_machine.o obj/path_planner.o obj/billing.o obj/logger.o obj/cli.o obj/sync.o obj/statistics.o obj/fault.o obj/scheduler.o obj/simulation.o

if %ERRORLEVEL% EQU 0 (
    echo Build successful! Run: bin\parking_garage.exe
) else (
    echo Build failed!
)
