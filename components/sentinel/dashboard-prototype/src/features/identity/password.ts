/** Narrow app entry; migration must not expose arbitrary-account password editing. */
export {
  createOwnPasswordWorkflow,
  type OwnPasswordWorkflow,
} from "./application/ownPasswordWorkflow";
export type { OwnPasswordPort, OwnPasswordReceipt } from "./api/ownPasswordPort";
export { OwnPasswordPage } from "./ui/OwnPasswordPage";
