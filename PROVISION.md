# Provisioning the bare-metal host (EC2 a1.metal, us-east-1)

The microVM work requires `/dev/kvm`, which only bare-metal EC2 instances expose. We use
`a1.metal` (Graviton1, 16 vCPU / 32 GB, ~$0.41/hr on-demand) in us-east-1.

```bash
REGION=us-east-1
AMI=$(aws ssm get-parameters --region $REGION \
  --names /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
  --query "Parameters[0].Value" --output text)

# keypair + security group locked to your IP (SSH + API:8080)
aws ec2 create-key-pair --region $REGION --key-name cw-poc-key \
  --query KeyMaterial --output text > cw-poc-key.pem && chmod 600 cw-poc-key.pem
MYIP=$(curl -s https://checkip.amazonaws.com)
SG=$(aws ec2 create-security-group --region $REGION --group-name cw-poc-sg \
  --description "CW microVM PoC" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG --protocol tcp --port 22   --cidr $MYIP/32
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG --protocol tcp --port 8080 --cidr $MYIP/32

# launch (a1.metal offers in us-east-1 a/b/c; fall back to c6g.metal on capacity, c5.metal for x86)
aws ec2 run-instances --region $REGION --image-id $AMI --instance-type a1.metal \
  --key-name cw-poc-key --security-group-ids $SG --associate-public-ip-address \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":80,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cw-microvm-poc}]'
```

## Host bootstrap (after SSH in as `ubuntu`)

```bash
sudo apt-get update -qq
sudo apt-get install -y zfsutils-linux jq netcat-openbsd bc psmisc acl
# Firecracker (aarch64)
REL=$(curl -s https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest | jq -r .tag_name)
curl -sSL https://github.com/firecracker-microvm/firecracker/releases/download/$REL/firecracker-$REL-aarch64.tgz | tar -xz
sudo cp release-$REL-aarch64/firecracker-$REL-aarch64 /usr/local/bin/firecracker
sudo usermod -aG kvm ubuntu     # reconnect SSH after this so the group takes effect

# prebuilt kernel + rootfs (skip image-building)
mkdir -p /opt/cw/base /opt/cw/run
B=https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/aarch64
curl -sSL $B/vmlinux-6.1.102      -o /opt/cw/base/vmlinux
curl -sSL $B/ubuntu-22.04.ext4    -o /opt/cw/base/rootfs-base.ext4
curl -sSL $B/ubuntu-22.04.id_rsa  -o /opt/cw/base/guest_key && chmod 600 /opt/cw/base/guest_key
```

## Gotchas hit during the PoC

- **`/dev/kvm` permission denied**: `ubuntu` must be in the `kvm` group (needs a fresh login) *or*
  `setfacl -m u:ubuntu:rw /dev/kvm`. Device ACLs get reset by udev/logind — `boot.sh`/`snaprestore.sh`
  re-apply the ACL on each launch as belt-and-suspenders.
- **Pause is `PATCH /vm`**, not `PUT`.
- **Clone rootfs ownership**: the golden image is root-owned; a ZFS clone inherits that, so Firecracker
  (running as `ubuntu`) can't open it read-write and the guest panics with `Cannot open root device`.
  `clone.sh` chowns the clone to `ubuntu` after cloning.
