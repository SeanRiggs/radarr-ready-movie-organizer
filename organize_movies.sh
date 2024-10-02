#!/bin/bash

# Directories where your movies are stored
MOVIE_DIRS=("/data/media/movies" "/data/media2/movies2")

# Function to display a progress bar
progress_bar() {
    local current=$1
    local total=$2
    local width=50
    local progress=$((current * width / total))
    local remain=$((width - progress))

    printf "\r["
    for ((i=0; i<progress; i++)); do printf "="; done
    for ((i=0; i<remain; i++)); do printf " "; done
    printf "] %d%%" $((current * 100 / total))
}

# Start processing the movie directories
for MOVIE_DIR in "${MOVIE_DIRS[@]}"; do
  # Check if the directory exists
  if [ -d "$MOVIE_DIR" ]; then
    echo "Processing movies in $MOVIE_DIR..."

    # Change to the movie directory
    cd "$MOVIE_DIR" || exit

    # Get the total number of movie files for progress tracking
    total_files=$(ls *.{mp4,mkv,avi,m4v} 2>/dev/null | wc -l)
    processed=0

    # Loop through each movie file
    for movie in *.{mp4,mkv,avi,m4v}; do
      # Check if it's a file (not a directory)
      if [ -f "$movie" ]; then
        # Get the filename without extension
        folder_name="${movie%.*}"

        # Create a folder with the same name as the movie (if it doesn't exist)
        mkdir -p "$folder_name"

        # Move the movie file into the new folder
        mv "$movie" "$folder_name"

        # Increment processed count and update progress bar
        processed=$((processed + 1))
        progress_bar $processed $total_files
      fi
    done

    echo -e "\nAll movies in $MOVIE_DIR have been organized into folders!"
  else
    echo "Directory $MOVIE_DIR does not exist!"
  fi
done

echo "All movies in both directories have been organized!"
