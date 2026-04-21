# pr132_scheduler_vm_report_data.json

Mocked fixture representing a Batch-vs-Scheduler comparison report (PR 132 style).
The original machine CSVs were not recovered, so the data is hand-crafted to exercise
the scheduler VM metrics path end-to-end.

## Terminology mapping (PR 132 scheduler VM -> Python renderer fields)

| PR 132 / old scheduler VM term          | Python renderer field              |
| ---------------------------------------- | ---------------------------------- |
| Scheduler booked CPU-hours               | `schedulerBookedCpuH`              |
| Scheduler rightsized CPU-hours           | `schedulerRightsizedCpuH`          |
| Scheduler overbook CPU-hours             | `schedulerOverbookCpuH`            |
| VM packing slack CPU-hours               | `vmPackingSlackCpuH`               |
| Scheduler allocation CPU efficiency %    | `schedAllocCpuEfficiency`          |
| Scheduler allocation memory efficiency % | `schedAllocMemEfficiency`          |
| Real VM CPU efficiency %                 | `realVmCpuEfficiency`              |
| Real VM memory efficiency %              | `realVmMemEfficiency`              |
| Requested VM CPU efficiency %            | `requestedVmCpuEfficiency`         |
| Requested VM memory efficiency %         | `requestedVmMemEfficiency`         |
| VM CPU-hours (total capacity)            | `vmCpuH`                           |
| VM memory GiB-hours (total capacity)     | `vmMemGibH`                        |
| Number of machines                       | `nMachines`                        |
| Group labels (`Batch-OnD`, `Sched-SpotFirst-Predv1`) | `group` field in each run |
