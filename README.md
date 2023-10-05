# NIG

## HOWTO Get started

#### Required installed softwares

- Python3.8+ (and pip)
- Docker 20+ with Compose v2
- Git


#### Clone the project

```
$ git clone https://gitlab.hpc.cineca.it/nig/nig-repository.git
$ cd nig-repository
$ git checkout 2.4
```

### Install the controller

```
$ sudo pip3 install --upgrade git+https://github.com/rapydo/do.git@2.4`

$ rapydo install
```

### Init & start

```
$ rapydo init
$ rapydo pull
$ rapydo build
$ rapydo start
```

First time it takes a while as it builds some docker images.

In dev mode you need to start api service by hand. Open a terminal and run  
`$ rapydo shell backend "restapi launch"`

Now open your browser and type http://localhost in the address bar.  
You will find the default credentials into the .projectrc file
