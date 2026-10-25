---
title: Connect Prometheus and host monitoring
summary: Collect and store first, then configure the console queries.
prerequisite: An admin account; a machine that can run the collector; network
  permission for the target.
outcome: Host curves show up, and you know which link to check when the data is empty.
---

## Host metrics and process metrics are different things

Host monitoring goes through a Prometheus-compatible backend with the profile node-exporter-v1. It sits on a completely different protocol layer from the rule profiles, so do not read the two through one shared support matrix.

| Host metric            | Meaning                                         | Scope |
| :--------------------- | :---------------------------------------------- | :---- |
| host_cpu_busy_ratio    | Host CPU busy ratio, a value between 0 and 1    | Host  |
| host_memory_used_bytes | Bytes of memory in use                          | Host  |
| host_memory_used_ratio | Share of memory in use, a value between 0 and 1 | Host  |
| host_load_1m           | Linux one-minute average load                   | Host  |

> **Note** node-exporter-v1 does not cover container metrics (that is cAdvisor's job), Windows metrics, disk and network health, or process metrics. host_load_1m can exceed the number of CPU cores; it is not a percentage and not a normalized saturation.

## Deploy the collector

Make the collection work first, then configure the console. Doing it the other way round is slow: when the console shows no curve you cannot tell whether collection failed or pairing failed.

1. Deploy node_exporter on the target machine.
2. Configure the scrape target in Prometheus.
3. In Prometheus' own interface, confirm that the target is up and that the metrics you need exist.
4. When running in a container, mount the host resources correctly; otherwise you collect the metrics of the container or virtual machine instead of the physical host.

## Register the monitoring source in the console

You register the query backend address of Prometheus, not the ingest address and not the collector's own /metrics address.

1. Allow the monitoring target on the deployment side, then register the monitoring target.
2. On the Connections and collection tab of system management, register the monitoring source: the Prometheus query address, the authentication method, the environment and the profile.
3. Test the connection and confirm that the probe result is usable.
4. Confirm that samples can be read — a successful connection does not mean there are samples in this time range.

> **Note** Exposing an Actuator endpoint on its own does not populate every application metric of this system. Either use the supported query mapping or connect a Reporter.

## Maintain the host-to-instance association

The mapping between hosts and running instances is maintained explicitly by an administrator; it is never inferred from hostnames or Prometheus labels.

1. Open the Host directory tab on the Applications and instances page.
2. Select a host.
3. In the running instance association area, add an association and fill in the application identifier and the instance identifier.
4. Once the association is confirmed, the resource curves of the host belong to the corresponding application.

> **Note** Unassociated hosts still appear in the directory. Switch to all applications to see the unassociated hosts. If an association is not confirmed, refresh the association list before retrying instead of submitting repeatedly.

## Connected but no curves

Check in this order; it covers the vast majority of cases.

1. Confirm that the scrape target is up and that Prometheus can return samples.
2. Confirm that the labels line up: host label, time label and instance identifier agree.
3. Confirm that the four metrics the profile needs all exist.
4. Confirm that the selected time range contains data instead of having just started to collect.
5. Confirm that the data is fresh and has not expired.
6. Finally, confirm that an explicit association exists between this instance and the host.

> **Note** Matching IP addresses alone do not make a host belong to an instance. The association is an explicitly maintained fact, not an inference.

## Where host and process metrics are shown

Process metrics and host metrics come from two entirely different paths and cover different scopes. The table below lists the scope and the location for each metric.

| Metric                 | Scope         | Where to see it                                  | Source                                                           |
| :--------------------- | :------------ | :----------------------------------------------- | :--------------------------------------------------------------- |
| cpu_ratio              | Process scope | Realtime, Applications and instances             | Process CPU reported by the Reporter                             |
| memory_ratio           | Process scope | Realtime, Applications and instances             | Process bytes in use and verified limit reported by the Reporter |
| memory_bytes           | Process scope | Realtime, Applications and instances             | Process RSS bytes reported by the Reporter                       |
| host_cpu_busy_ratio    | Host scope    | Host directory, host resource trends in Realtime | node-exporter-v1 queried through Prometheus                      |
| host_memory_used_bytes | Host scope    | Host directory, host resource trends in Realtime | node-exporter-v1 queried through Prometheus                      |
| host_memory_used_ratio | Host scope    | Host directory, host resource trends in Realtime | node-exporter-v1 queried through Prometheus                      |
| host_load_1m           | Host scope    | Host directory, host resource trends in Realtime | node-exporter-v1 queried through Prometheus                      |

> **Note** The two are counted separately and never fill in for each other. When process metrics are not integrated they show "not integrated", and when host metrics have no samples in the time range they show "no samples"; neither side borrows the other's numbers. host_load_1m can exceed the number of CPU cores; it is not a percentage and it has no aggregation base.

## Further reading

- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
