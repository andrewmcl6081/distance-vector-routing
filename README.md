# Distance Vector Routing Simulator

## Overview

This python script simulates the behavior of the distance vector routing algorithm across a network of connected nodes. It dynamically calculates and updates the cost of reaching all other nodes from a given node using the Bellman-Ford equation and an input file that represents the network topology with costs to reaching other nodes. The simulation supports an automatic and single-step mode, to observe the routing table updates in real-time or step-by-step.

## Features

- **Dynamic Routing Simulation:** Simulates the distance vector routing algorithm, allowing for dynamic updates based on network changes.
- **Two Modes of Operation:** Supports automatic and single-step modes for flexible observations of routing updates.
- **Threaded Simulation:** Utilizes Python's threading capabilities to simulate concurrent operations across multiple network nodes.
- **Socket Communication:** Threads communicate and send their distance vectors to their neighbors upon updates using sockets
- **Customizable Network Topology:** Reads an initial network configuration from an `input.txt` file, allowing for easy customization of the network topology.
- **Graceful Shutdown:** Provides mechanisms for a clean shutdown of all node simulations and networking threads upon completion or reaching a stable state.

## Requirements

- Python 3.6 or later

## Setup

1. **Clone the Repository:**
     Clone this repository to your local machine using `git clone` or download the ZIP file.

2. **Prepare the Input File:**
   Create an `input.txt` file in the same directory as the script with your network topology. Each line in the file should represent a connection between two nodes and the cost, formatted as `node1 node2 cost`

3. **Run the Script:**
Navigate to the directory containing the script and run it using Python.
```bash
python distance_vector_routing.py
