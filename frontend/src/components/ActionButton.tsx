import { Button, buttonVariants } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAction } from "@/lib/rekuest/task";
import { type ActionDefinition } from "@/lib/rekuest/task/types";
import { type AssignOptions } from "@/lib/rekuest/transport/types";
import { cn } from "@/lib/utils";
import { type VariantProps } from "class-variance-authority";
import React, { type ButtonHTMLAttributes } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

/** Generate a unique local reference */
function generateReference(): string {
  return `ref-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

interface ActionButtonProps<TArgs, TReturn>
  extends
    Omit<ButtonHTMLAttributes<HTMLButtonElement>, "action" | "onError">,
    VariantProps<typeof buttonVariants> {
  action: ActionDefinition<TArgs, TReturn>;
  args: TArgs;
  step?: boolean; // Optional prop to indicate if we should step and pause on the first pausepoint
  assignOptions?: AssignOptions;
  children?: React.ReactNode;
}

export function ActionButton<TArgs, TReturn>({
  action,
  args,
  assignOptions,
  className,
  variant,
  size,
  step,
  children,
  onClick,
  disabled,
  ...props
}: ActionButtonProps<TArgs, TReturn>) {
  const { t } = useTranslation();
  const actionApi = useAction(action);

  const handleClick = async (e: React.MouseEvent<HTMLButtonElement>) => {
    onClick?.(e);
    if (e.isDefaultPrevented()) return;

    // Check if any lockKey has an active task
    if (actionApi.isLocked) {
      toast.warning(t("microscope.actionLocked"), {
        description: t("microscope.actionLockedDescription", {
          task: actionApi.lockedBy ?? "?",
        }),
      });
      return;
    }

    // Generate a local reference before assignment
    const reference = generateReference();

    try {
      console.log(
        "Assigning action:",
        action.name,
        "with args:",
        args,
        "reference:",
        reference,
      );
      const task = await actionApi.assign(args, {
        ...assignOptions,
        reference,
        step,
      });
      console.log("Assigned task:", task);
    } catch (e) {
      console.error(e);
      if (e instanceof Error) {
        toast.error(t("microscope.actionFailed", { action: action.name }), {
          description: e.message,
        });
      }
    }
  };

  const button = (
    <Button
      variant={variant}
      size={size}
      className={cn(className)}
      disabled={disabled || actionApi.isLocked}
      onClick={handleClick}
      data-locked={actionApi.isLocked ? "true" : "false"}
      data-blocking-task={actionApi.lockedBy || "unknown"}
      {...props}
    >
      {children || action.name}
    </Button>
  );

  // If locked, wrap in tooltip showing the blocking task
  if (actionApi.isLocked && !disabled) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent>
            {t("microscope.actionLockedTooltip", {
              task: actionApi.lockedBy || "?",
            })}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return button;
}
