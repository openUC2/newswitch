export const getScopedTaskReference = (appKey: string, reference: string) =>
  `${appKey}::task-ref::${reference}`;

export const getScopedTaskId = (appKey: string, taskId: string) =>
  `${appKey}::task-id::${taskId}`;
