import React from 'react';
import { useQuery, useMutation, gql } from '@apollo/client';
import { DragDropContext, Droppable, Draggable, DropResult } from 'react-beautiful-dnd';

const GET_TASKS = gql`
  query GetTasks {
    tasks {
      id
      title
      columnId
    }
    columns {
      id
      name
    }
  }
`;

const MOVE_TASK = gql`
  mutation MoveTask($taskId: ID!, $columnId: ID!) {
    moveTask(taskId: $taskId, columnId: $columnId) {
      id
      columnId
    }
  }
`;

interface Task { id: string; title: string; columnId: string; }
interface Column { id: string; name: string; }

const Board: React.FC = () => {
  const { loading, error, data } = useQuery(GET_TASKS);
  const [moveTask] = useMutation(MOVE_TASK);

  if (loading) return <p>Loading...</p>;
  if (error) return <p>Error loading tasks.</p>;

  const columns: Column[] = data.columns;
  const tasks: Task[] = data.tasks;

  const onDragEnd = async (result: DropResult) => {
    const { destination, source, draggableId } = result;
    if (!destination || destination.droppableId === source.droppableId) return;
    await moveTask({ variables: { taskId: draggableId, columnId: destination.droppableId } });
  };

  const tasksByColumn = columns.reduce((acc, col) => {
    acc[col.id] = tasks.filter((t) => t.columnId === col.id);
    return acc;
  }, {} as Record<string, Task[]>);

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <div style={{ display: 'flex', gap: '10px' }}>
        {columns.map((col) => (
          <Droppable droppableId={col.id} key={col.id}>
            {(provided) => (
              <div
                ref={provided.innerRef}
                {...provided.droppableProps}
                style={{ background: '#f4f5f7', padding: '10px', width: '250px', minHeight: '400px' }}
              >
                <h3>{col.name}</h3>
                {tasksByColumn[col.id].map((task, index) => (
                  <Draggable draggableId={task.id} index={index} key={task.id}>
                    {(provided) => (
                      <div
                        ref={provided.innerRef}
                        {...provided.draggableProps}
                        {...provided.dragHandleProps}
                        style={{
                          userSelect: 'none',
                          padding: '8px',
                          margin: '0 0 8px 0',
                          background: '#fff',
                          ...provided.draggableProps.style,
                        }}
                      >
                        {task.title}
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        ))}
      </div>
    </DragDropContext>
  );
};

export default Board;
