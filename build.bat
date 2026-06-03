@echo off
REM Build script for Smart Parking Garage System
REM Requires gcc (MinGW) in PATH

if not exist obj mkdir obj
if not exist bin mkdir bin

echo Compiling...
gcc -std=c11 -Wall -Wextra -I./include -c src/main.c -o obj/main.o
gcc -std=c11 -Wall -Wextra -I./include -c src/garage.c -o obj/garage.o
gcc -std=c11 -Wall -Wextra -I./include -c src/state_machine.c -o obj/state_machine.o
gcc -std=c11 -Wall -Wextra -I./include -c src/path_planner.c -o obj/path_planner.o
gcc -std=c11 -Wall -Wextra -I./include -c src/billing.c -o obj/billing.o
gcc -std=c11 -Wall -Wextra -I./include -c src/logger.c -o obj/logger.o
gcc -std=c11 -Wall -Wextra -I./include -c src/cli.c -o obj/cli.o

echo Linking...
gcc -o bin/parking_garage.exe obj/main.o obj/garage.o obj/state_machine.o obj/path_planner.o obj/billing.o obj/logger.o obj/cli.o

if %ERRORLEVEL% EQU 0 (
    echo Build successful! Run: bin\parking_garage.exe
) else (
    echo Build failed!
)
