import json
import time
from datetime import datetime, timedelta
import subprocess

def load_tasks():
    try:
        with open("scheduled_tasks.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def should_run_task(task, current_time):
    start_time = datetime.strptime(task["start_time"], "%Y-%m-%d %H:%M:%S")
    if current_time < start_time:
        return False

    interval = task["interval"]
    if interval == "Daily":
        return (current_time - start_time).days >= 1
    elif interval == "Weekly":
        return (current_time - start_time).days >= 7
    elif interval == "Monthly":
        return (current_time.year, current_time.month) != (start_time.year, start_time.month)

    return False

def execute_task(task):
    # Here you would implement the logic to execute the task
    # For demonstration, we'll just print the task details
    print(f"Executing task: {task}")
    # You might want to call your main script here, passing the necessary arguments
    # subprocess.run(["python", "your_main_script.py", task["file_path"], task["prompt"]])

def main():
    while True:
        current_time = datetime.now()
        tasks = load_tasks()

        for task in tasks:
            if should_run_task(task, current_time):
                execute_task(task)
                # Update the last run time
                task["start_time"] = current_time.strftime("%Y-%m-%d %H:%M:%S")

        # Save updated tasks
        with open("scheduled_tasks.json", "w") as file:
            json.dump(tasks, file, indent=2)

        # Sleep for a minute before checking again
        time.sleep(60)

if __name__ == "__main__":
    main()