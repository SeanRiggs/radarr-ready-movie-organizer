# 📁 Organize Movies Into Folders: Radarr-Ready Movie Collection! 🎉

## 🚨 The Problem:
Your movie library is a wild west of loose files—tons of them sitting outside of folders, and Radarr is sitting there, unable to import because, guess what, **Radarr needs each movie in its own folder**. 😩 Managing it all manually? No, thanks.

## 💡 The Solution:
This script will **automatically** organize your movies into neat little folders, making sure that **Radarr can easily scan and import** everything. 📂🎬 It creates a folder for each movie, moves the file into that folder, and gives you a beautifully organized library that's fully Radarr-compliant! ✅

---

## 🌟 Features:
- **Automates folder creation** for all your movie files. 🎬🗂️
- **Radarr integration**: Ensures that Radarr can successfully import your movies by putting them in folders! 🤖✨
- **Progress bar included**: Watch the magic unfold as it processes your entire collection. 💫

---

## 🚀 How to Use:
1. **Save the script**: Place the script somewhere on your server (e.g., `/opt/organize_movies.sh`).
2. **Edit directories**: Update the `MOVIE_DIRS` array with your movie folder locations. 🎥
3. **Run the script**:


```bash
bash /opt/organize_movies.sh
```

# 📁 The Script:
```bash
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
```

# 🛠 Why This Is Radarr Gold:
- *Radarr Requires Folders:* This script ensures each movie gets its own folder, a requirement for Radarr to import and manage your library without hiccups. 💼
- *Save Time:* No more manual folder creation! 🕒 Just run the script and let it organize your entire movie collection with minimal effort. 💪

# 🎉 Your Library, Radarr-Ready and Super Organized!
By running this script, you're taking your movie library from chaos to order. 📂 Now your movies are stored in individual folders, Radarr can scan, import, and do its job perfectly, and you get the satisfaction of an organized media collection. It's a win-win-win! 🎬🍿✨

