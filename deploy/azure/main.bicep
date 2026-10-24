@description('Short, globally unique suffix used only for the app and environment names.')
@minLength(4)
@maxLength(12)
param nameSuffix string

@description('Azure region approved by the account preflight.')
param location string

@description('Immutable container image reference, including sha256 digest.')
@minLength(75)
param imageReference string

@description('Git commit recorded in deployment tags.')
param gitCommit string

@description('Selected release bundle SHA-256 recorded in deployment tags.')
@minLength(64)
@maxLength(64)
param modelSha256 string

var project = 'game-discovery'
var environmentName = '${project}-${nameSuffix}-env'
var appName = '${project}-${nameSuffix}'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: {
    project: project
    owner: 'game-discovery-ml'
  }
  properties: {
    appLogsConfiguration: { destination: 'none' }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: {
    project: project
    owner: 'game-discovery-ml'
    gitCommit: gitCommit
    modelSha256: modelSha256
  }
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
        traffic: [{ latestRevision: true, weight: 100 }]
      }
      registries: []
      secrets: []
    }
    template: {
      containers: [
        {
          name: 'game-discovery'
          image: imageReference
          env: [
            { name: 'PORT', value: '8080' }
            { name: 'FEEDBACK_ENABLED', value: 'false' }
            { name: 'OMP_NUM_THREADS', value: '1' }
            { name: 'OPENBLAS_NUM_THREADS', value: '1' }
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/readyz', port: 8080, scheme: 'HTTP' }
              initialDelaySeconds: 10
              periodSeconds: 10
              failureThreshold: 18
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8080, scheme: 'HTTP' }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          { name: 'http-concurrency', http: { metadata: { concurrentRequests: '10' } } }
        ]
      }
    }
  }
}

output appName string = app.name
output environmentName string = environment.name
