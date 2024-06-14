from collections import deque
from copy import deepcopy
from .and_or_graphs import AndOrGraph, NodeType, ContentType  # Ensure this is correctly imported
from .sccs import SCCDetection
# store landmarks, needed when landmarks are updated for each new node
class LM_Node:
    def __init__(self, len_nodes, parent=None):
        if parent:
            self.lms = parent.lms
            self.mark = parent.mark
            self.number_lms = parent.number_lms
            self.achieved_lms = parent.achieved_lms
        else:
            self.lms  = 0
            self.mark = 0
            self.number_lms   = 0   # total number of lms
            self.achieved_lms = 0   # total achieved lms
            

    # mark as 'achieved' if node is a lm
    def mark_lm(self, node_id):
        if self.lms & (1 << node_id) and ~self.mark & (1 << node_id):
            self.mark |= 1 << node_id
            self.achieved_lms+=1
        
            
    # add new lms
    def update_lms(self, new_lms):
        for lm_id in new_lms:
            if ~self.lms & (1 << lm_id):
                self.lms |= (1 << lm_id)
                self.number_lms+=1
        
    def lm_value(self):
        return self.number_lms - self.achieved_lms
    
    def __str__(self):
        #lms_bin = format(self.lms, '0{}b'.format(len(str(bin(self.lms)))-2))[::-1]  # -2 to remove '0b'
        #achieved_bin = format(self.mark, '0{}b'.format(len(str(bin(self.mark)))-2))[::-1]
        return f"Lms (value={self.lm_value()}): \n\tlms:      {bin(self.lms)}\n\tachieved: {bin(self.mark)}"

class Landmarks:
    def __init__(self, model):
        self.bu_AND_OR = AndOrGraph(model, top_down=False) # bottom-up and or graph
        self.td_AND_OR = AndOrGraph(model, top_down=True)  # top-down and or graph
        
        self.len_landmarks = len(self.bu_AND_OR.nodes)
        self.bu_landmarks    = [set()] * self.len_landmarks # bottom-up landmarks
        self.td_landmarks    = [set()] * self.len_landmarks # top-down landamarks
        
    '''
        Original landmark extraction:
          We refer to it as 'bottom-up landmarks' because it captures the HTN hierarchy this way
          see: Höller, D., & Bercher, P. (2021). Landmark Generation in HTN Planning. Proceedings of the AAAI Conference on Artificial Intelligence
    '''
    def bottom_up_lms(self):
        queue = deque([node for node in self.bu_AND_OR.nodes if len(node.predecessors) == 0])
        while queue:
            node = queue.popleft()
            new_landmarks= set()
            
            if node.type == NodeType.OR and node.predecessors:
                new_landmarks = set.intersection(*(self.bu_landmarks[pred.ID] for pred in node.predecessors))
                
            elif node.type == NodeType.AND and node.predecessors:
                new_landmarks = set.union(*(self.bu_landmarks[pred.ID] for pred in node.predecessors))
                
            new_landmarks = new_landmarks | {node.ID}
            if  new_landmarks > self.bu_landmarks[node.ID]:
                self.bu_landmarks[node.ID] = new_landmarks
                for succ in node.successors:
                    if all(len(self.bu_landmarks[pred.ID])!=None for pred in succ.predecessors):
                        queue.append(succ)

    '''
        top-down landmarks extraction, our proposed works:
            (1) use a AND OR graph with inverted arcs at tasks and methods -operators and facts are the same
            (2) considering 'Operator' nodes as a sort of a hybrid node: for facts its 'AND' node, for methods its an 'OR' node.
            (3) extract landmarks using this graph.
    '''
    def top_down_lms(self):
        #queue = deque([self.td_AND_OR.nodes[node_id] for node_id in self.td_AND_OR.i_node_set])
        queue = deque([node for node in self.td_AND_OR.nodes if len(node.predecessors) == 0])
        dot_visited = set()
        while queue:
            node = queue.popleft()
            new_landmarks   = set()
            dot_visited    |= {node.ID}
            # dot_successors  = {succ.ID for succ in node.successors}
            # dot_newlms      = {}
            # dot_existinglms = {}
            
            if node.content_type == ContentType.OPERATOR and node.predecessors:
                possible_method_landmarks = []
                forced_landmarks = set()
                for pred in node.predecessors:
                    if pred.content_type == ContentType.METHOD:
                        possible_method_landmarks.append(self.td_landmarks[pred.ID])
                    else:
                        forced_landmarks |= self.td_landmarks[pred.ID]
                
                if possible_method_landmarks:
                    new_landmarks = set.intersection(*(i for i in possible_method_landmarks)) 
                    
            elif node.type == NodeType.OR and node.predecessors:
                new_landmarks = set.intersection(*(self.td_landmarks[pred.ID] for pred in node.predecessors))
            elif node.type == NodeType.AND and node.predecessors:
                new_landmarks = set.union(*(self.td_landmarks[pred.ID] for pred in node.predecessors))
            
            new_landmarks|= {node.ID}
            
            # NOTE: need proof on termination
            if  new_landmarks != self.td_landmarks[node.ID]:
                self.td_landmarks[node.ID] = new_landmarks

                #dot_existinglms = self.landmarks[node.ID]
                #dot_newlms = new_landmarks - self.landmarks[node.ID]
                # self.and_or_graph.dot_output_step(
                #     current_node=node.ID, 
                #     successors=dot_successors, 
                #     new_landmarks=dot_newlms, 
                #     visited= dot_visited,
                #     existing_landmarks=dot_existinglms
                # )

                for succ in node.successors:
                    if all(len(self.td_landmarks[pred.ID])!=None for pred in succ.predecessors):
                        queue.append(succ)
        
    def bidirectional_lms(self, model, state, task_network):
        """
        Combination of bottom-up landmarks w/ top-down landmarks:
            - refine operators found by bottom-up landmarks using top-down landmarks
            - refine methods found by top-down landmarks using bottom-up landamrks
            - repeat until exausting every possible refinment 
        Args:
            model (Model): The planning model.
            state (int): Bitwise representation of the current state.
            task_network (list): List of tasks in the task network.

        Returns:
            set: Set of computed landmarks.
        """
        bid_landmarks = set()
        visited   = set()
        queue     = deque()
        # Precompute landmarks based on the initial state and goal conditions
        for fact_pos in range(len(bin(model.goals))-2):
            if model.goals & (1 << fact_pos) and ~state & (1 << fact_pos):
                for lm in self.bu_landmarks[fact_pos]:
                    bid_landmarks.add(lm)
            if state & (1 << fact_pos):
                bid_landmarks.add(fact_pos)
        
        # Add landmarks related to each task in the task network
        for t in task_network:
            for lm in self.bu_landmarks[t.global_id]:
                bid_landmarks.add(lm)
        
        for lm_id in bid_landmarks:
            node = self.bu_AND_OR.nodes[lm_id]
            if node.content_type == ContentType.OPERATOR:
                queue.append(node.ID)
            elif node.content_type == ContentType.FACT and ~state & (1 << lm_id):
                queue.append(node.ID)
            else:
                visited.add(node.ID)
        
        while queue:
            node_id = queue.popleft()
            visited.add(node_id)
            bid_landmarks.add(node_id)
            node = self.bu_AND_OR.nodes[node_id]
            
            for lm_id in self.td_landmarks[node.ID]:
                if not lm_id in visited:
                    queue.append(lm_id)
            
            for lm_id in self.bu_landmarks[node.ID]:
                if not lm_id in visited:
                    queue.append(lm_id)
        return bid_landmarks

    # UTILITARY
    # def print_landmarks(self, node_id):
    #     print(f'SPECIFIC landmarks of {self.and_or_graph.nodes[node_id]}')
    #     for lm in self.landmarks[node_id]:
    #         print(f'\tlm: {self.and_or_graph.nodes[lm]}')

# if __name__ == '__main__':
#     graph = AndOrGraph(None, debug=True)  # Ensure correct initialization
#     lm = Landmarks(graph)
#     lm.generate_lms()
#     for node_id, lms in enumerate(lm.landmarks):
#         print(f"node{node_id} {lm.nodes[node_id]}")
#         for lm_id in lms:
#             print(f"\tlm {lm.nodes[lm_id]}")
