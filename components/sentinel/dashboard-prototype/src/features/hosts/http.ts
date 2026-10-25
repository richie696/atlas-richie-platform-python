/** HTTP contracts and adapter exports for app-level Console API assembly. */
export {
  HOST_ASSOCIATION_HTTP_CONTRACT,
  createHostAssociationHttp,
} from "./api/hostAssociationHttp";
export type {
  HostAssociation,
  HostAssociationDirectory,
  HostAssociationInput,
  HostAssociationOperation,
} from "./application/hostAssociationPort";
