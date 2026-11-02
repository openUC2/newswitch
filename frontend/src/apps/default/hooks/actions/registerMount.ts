import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const RegisterMountArgsSchema = z.object({
  /** 4x4, stage micrometres to sample micrometres. */
  matrix: z
    .array(z.array(z.number()))
    .describe('4x4, stage micrometres to sample micrometres.'),
});
export const RegisterMountReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type RegisterMountArgs = z.input<typeof RegisterMountArgsSchema>;
export type RegisterMountReturn = z.infer<typeof RegisterMountReturnSchema>;

// --- Definition ---
export const RegisterMountDefinition: ActionDefinition<
  RegisterMountArgs,
  RegisterMountReturn
> = {
  name: 'register_mount',
  appKey: 'default',
  description: 'Say where what is mounted sits on the stage.',
  argsSchema: RegisterMountArgsSchema,
  returnSchema: RegisterMountReturnSchema,
  lockKeys: [],
};

/**
 * Say where what is mounted sits on the stage.
 */
export const useRegisterMount = () => {
  return useAction(RegisterMountDefinition);
};
