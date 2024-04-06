from datetime import datetime
import threading
import socket
import json
import copy
import time
import sys

node_update_status_lock = threading.Lock()
node_update_lock = threading.Lock()
connections_lock = threading.Lock()
updates_lock = threading.Lock()

send_vectors_event = threading.Event()
shutdown_event = threading.Event()
proceed_event = threading.Event()
update_pause_barrier_ss = None
update_pause_barrier_a = None

last_update_time = None
start_time = None
end_time = None

active_connections = []
distance_vectors = {}
node_update_status = {}
update_counter = 0
base_port = 5000

def initialize(file_name):
    global node_update_status, update_pause_barrier_ss, update_pause_barrier_a
    neighbors = {}
    network_map = {}
    nodes = set()
    
    # open input.txt file
    with open(file_name, "r") as file:
        for line in file:
            # get nodes and cost from line
            node1, node2, cost = map(int, line.strip().split())
            
            # add nodes to nodes
            nodes.add(node1)
            nodes.add(node2)
            
            # add nodes to network_map
            if node1 not in network_map:
                network_map[node1] = {}
            if node2 not in network_map:
                network_map[node2] = {}
            
            network_map[node1][node2] = cost
            network_map[node2][node1] = cost
    
    # for each node assign a set of neighbors
    for node in network_map:
        neighbors[node] = set()
        
        for neighbor in network_map[node]:
            neighbors[node].add(neighbor)
        
    # set the missing destination nodes that arent known to infinity and set distance to self to 0
    for node in network_map:
        for x in nodes:
            if x not in network_map[node] and x != node:
                network_map[node][x] = float("inf")
            
            if node == x:
                network_map[node][x] = 0
    
    # initialize each node as initially updated so the program doesnt stop right off the bat
    for node in nodes:
        node_update_status[node] = True
    
    # initialize the barrier with one extra for the main control thread for single-step but no extra for automatic since
    # it does not rely on the main thread to be controlled
    update_pause_barrier_ss = threading.Barrier(len(nodes) + 1)
    update_pause_barrier_a = threading.Barrier(len(nodes))
    
    return network_map, neighbors, len(nodes)

def update_distance_vectors(node_id, node_dv, dv_update_batch, neighbors, mode):
    global node_update_status, proceed_event, update_pause_barrier_ss, update_pause_barrier_a, distance_vectors, shutdown_event, last_update_time
    source = node_id
    modified = False
    
    for neighbor_id, neighbor_dv in dv_update_batch:
        # if we have a dictionary as the second tuple item then we have a distance vector to update with
        if isinstance(neighbor_dv, dict):
            for destination, cost in neighbor_dv.items():
                # dont check if source and destination are the same
                if destination != source:
                    # cost from current node to neighbor + cost from neighbor to destination
                    new_cost = node_dv[neighbor_id] + cost
                    
                    # if our new cost is less than our original, update
                    if new_cost < node_dv[destination]:
                        node_dv[destination] = new_cost
                        modified = True
    
    # if we modified a distance vector update the global table
    if modified:
        with node_update_lock:
            distance_vectors[node_id] = copy.deepcopy(node_dv)
    
    if mode == "single-step":
        # update the node's status based on whether there was an update to it or not
        with node_update_status_lock:
            node_update_status[node_id] = modified
        
        # wait for all single step threads to reach this point
        # print(f"Node: {node_id} waiting at update_pause_barrier in udv function")
        update_pause_barrier_ss.wait()
        
        # run until shutdown_event is set
        while not shutdown_event.is_set():
            # if proceed_event is set within 1 second break out and continue tasks otherwise
            # continue to monitor until we are told its time to shutdown or are given the
            # green light to continue
            if proceed_event.wait(timeout=1):
                break
        
        if shutdown_event.is_set():
            return
    else:
        if modified:
            with updates_lock:
                last_update_time = datetime.now()
        
        update_pause_barrier_a.wait()
    
    if modified:
        send_dv_to_neighbors(node_id, node_dv, neighbors, True)
    else:
        send_dv_to_neighbors(node_id, node_dv, neighbors, False)

def shutdown():
    with connections_lock:
        for conn in active_connections:
            try:
                conn.close()
            except Exception as e:
                print(f"Error closing connection: {e}")
        active_connections.clear()

def listen_for_dv_updates(node_id, host, port, node_dv, neighbors, mode):
    # keep track of which nodes have sent their updates
    received_updates = set()
    
    # this array maintains tuples of (received_node_id, either distance vector or "no_update")
    dv_updates_batch = []
    
    # listen for incoming distance vectors from neighbors
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen()
        
        # wait up to 2 seconds before triggering a socket timeout leading to checking
        # if shutdown event is set
        s.settimeout(2)
        
        # accept connections while shutdown event hasnt occured
        while not shutdown_event.is_set():
            try:
                conn, addr = s.accept()
                
                with connections_lock:
                    active_connections.append(conn)
                    
                with conn:
                    data = conn.recv(1024)
                    
                    # if we received data
                    if data:
                        # decode message
                        message = json.loads(data.decode("utf-8"))
                        
                        received_node_id = message["node_id"]
                        received_dv = message["dv"]
                        
                        # add node that sent their update to set so we know who has checked in
                        received_updates.add(received_node_id)
                        
                        # if the received distance vector is deemed to not have been updated state so in the update batch
                        if message["updated"] == False or message["updated"] == "False":
                            dv_updates_batch.append((received_node_id, "no_update"))
                        # if the received dv has been updated process and add it to the batch
                        else:
                            converted_received_dv = {int(key): value for key, value in received_dv.items()}
                            dv_updates_batch.append((received_node_id, converted_received_dv))
                
                # if all our neighbors have sent us some form of an update, process the updates  
                if len(received_updates) == len(neighbors[node_id]):
                    # create a deep copy of the batch so we can send it out to be updated and be able to clear the original batch so we can be ready to receive new batches
                    temp_batch = copy.deepcopy(dv_updates_batch)
                    received_updates.clear()
                    dv_updates_batch.clear()
                    
                    update_distance_vectors(node_id, node_dv, temp_batch, neighbors, mode)
                    
            except socket.timeout:
                continue

def send_dv_to_neighbors(node_id, node_dv, neighbors, updated):
    # wait for input from GUI to start sending our initial distance vectors (first iteration)
    send_vectors_event.wait()
    
    time.sleep(0.05)
    
    if shutdown_event.is_set():
        return
    
    # send distance vector to all neighbors
    for neighbor in neighbors[node_id]:
        port = neighbor + base_port
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", port))
                
                message = {
                    "node_id": node_id,
                    "dv": node_dv,
                    "updated": updated
                }
                
                encoded_message = json.dumps(message).encode('utf-8')
                
                s.sendall(encoded_message)
        except ConnectionError as e:
            print(f"Node {node_id} failed to send DV table to Node {neighbor}: {e}")

def control_execution_single_step():
    global proceed_event, update_pause_barrier_ss, shutdown_event
    
    while not shutdown_event.is_set():
        # wait for all node threads to reach the barrier, including the main thread
        update_pause_barrier_ss.wait()
        
        # check to see if any updates have occured at the end of an iteration
        no_updates = None
        with node_update_status_lock:
            no_updates = not any(node_update_status.values())
            
            if no_updates == True:
                print("The system has reached a stable state.")
                shutdown_event.set()
                shutdown()
                break
        
        print_distance_vectors()
        
        input("Press enter to proceed to the next iteration")
        
        # allow threads to continue and clear event for next iteration
        proceed_event.set()
        proceed_event.clear()

def check_for_stability_in_automatic():
    global end_time
    
    # continuosuly check if we updated vectors longer than 2 seconds ago
    while True:
        with updates_lock:
            if (datetime.now() - last_update_time).total_seconds() > 2:
                print("The system has reached a stable state.")
                
                end_time = datetime.now()
                shutdown_event.set()
                shutdown()
                break
        time.sleep(1)
        
def node_thread(node_id, node_dv, neighbors, start_barrier, mode):
    port = base_port + node_id
    
    # create a seperate server thread inside the node thread that listens for distance vector updates
    server_thread = threading.Thread(target=listen_for_dv_updates, args=(node_id, "127.0.0.1", port, node_dv, neighbors, mode))
    server_thread.start()
    
    # wait for all threads to reach this point (servers set up and listening) before continuing
    start_barrier.wait()
    
    # send our initial distance vectors to all our neighbors
    send_dv_to_neighbors(node_id, node_dv, neighbors, True)

def print_distance_vectors():
    global distance_vectors
    
    with node_update_lock:
        for node_id, dv in distance_vectors.items():
            print(f"Node {node_id}")
            for destination, cost in dv.items():
                print(f"-- Node {destination}: Cost {cost}")

if __name__ == "__main__":   
    network_map, neighbors, total_nodes = initialize(sys.argv[1])
    start_barrier = threading.Barrier(total_nodes)
    
    # display the starting configuration to user
    print("Starting network map configuration")
    for node_id, dv in network_map.items():
        print(f"Node {node_id}")
        for destination, cost in dv.items():
            print(f"-- Node {destination}: Cost {cost}")
    
    # get the mode of operation from the user
    mode = input("Select mode (automatic or single-step): ").strip().lower()
    
    # declare and start our threads assigning each node a distance vector copy
    threads = []
    for node_id in network_map:
        node_dv = copy.deepcopy(network_map[node_id])
    
        thread = threading.Thread(target=node_thread, args=(node_id, node_dv, neighbors, start_barrier, mode))
        thread.start()
        threads.append(thread)
        
    # trigger the sending of distance vectors
    input("Press enter to start execution")
    send_vectors_event.set()
    
    # handle automatic and single step modes
    if mode == "automatic":
        with updates_lock:
            last_update_time = datetime.now()
            start_time = datetime.now()
        
        stability_thread = threading.Thread(target=check_for_stability_in_automatic)
        stability_thread.start()
        stability_thread.join()
    else:
        control_execution_single_step()
    
    # clean up and join threads
    for thread in threads:
        thread.join()
    
    # display final results to user
    print("Stabalized distance vectors:")
    print_distance_vectors()
    
    # display elapsed time to user only if in automatic mode
    if mode == "automatic":
        print(f"Total elapsed time: {(end_time - start_time).total_seconds()}")