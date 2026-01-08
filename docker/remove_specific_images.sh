#!/bin/bash
PROJ=scipy
dry_run=false

# Comprehensive exclusion list
EXCLUDE_LIST=(
    24056
    24092
    24118
    24119
    24133
    24134
    24172
    24179
    24185
    24234
)

# Function to check if a number is in the exclusion list
is_excluded() {
  local number=$1
  for excluded in "${EXCLUDE_LIST[@]}"; do
    if [[ "$excluded" == "$number" ]]; then
      return 0
    fi
  done
  return 1
}

# Fetch all Docker images starting with the prefix "qiskit-pr-"
IMAGES=$(docker images --format "{{.Repository}}" | grep "^$PROJ-pr-")
# List all images to be removed
TO_REMOVE=()
for image in $IMAGES; do
    # Extract the number from the image name
    number=$(echo "$image" | sed "s/$PROJ-pr-//")

    # Check if the number is in the exclusion list
    if is_excluded "$number"; then
        echo "Skipping image: $image (excluded)"
        continue
    fi

    # Add the image to the removal list
    TO_REMOVE+=("$image")
done

# Display images to be removed
echo "Images to be removed:"
for image in "${TO_REMOVE[@]}"; do
    echo "$image"
done

if [ "$dry_run" = true ]; then
    echo "Dry run enabled. No images will be removed."
    exit 0
fi

# Iterate through the images and remove them
for image in "${TO_REMOVE[@]}"; do
    # Prompt the user for confirmation
    read -p "Do you want to remove the image $image? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        docker rmi "$image"
        echo "Removed image: $image"
    else
        echo "Skipping image: $image"
    fi
done
