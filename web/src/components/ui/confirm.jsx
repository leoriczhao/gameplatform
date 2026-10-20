import * as React from "react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "./alert-dialog.jsx";

/* Confirmation dialog wrapped around any trigger — replaces antd Popconfirm.
   <Confirm title="..." description="..." onConfirm={fn} danger>
     <Button>删除</Button>
   </Confirm> */
function Confirm({ title = "确认操作", description, confirmText = "确认", cancelText = "取消", onConfirm, danger = true, children, ...props }) {
  return (
    <AlertDialog {...props}>
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelText}</AlertDialogCancel>
          <AlertDialogAction
            variant={danger ? "destructive" : "default"}
            onClick={(e) => {
              if (onConfirm) onConfirm(e);
            }}
          >
            {confirmText}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export { Confirm };
